"""
Admin API Routes — Staff review console endpoints.

All endpoints are prefixed with /admin/api/.
The admin HTML page is served at /admin/.
"""

import os
import sys
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse

from app.services.audit_log import (
    get_recent_events,
    get_conversation,
    get_conversations_summary,
    get_query_log,
    get_stats,
    get_eval_results,
    load_eval_results_from_file,
    set_eval_results,
)

logger = logging.getLogger(__name__)

# Tracks whether an eval run is currently in progress
_eval_running = False
_eval_status: dict = {}
_eval_lock = threading.Lock()

router = APIRouter(prefix="/admin", tags=["admin"])

# Path to the eval runner (relative to project root)
TESTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tests"

# Path to the admin frontend
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent.parent / "frontend"


# ---------------------------------------------------------------------------
# ADMIN FRONTEND
# ---------------------------------------------------------------------------

@router.get("/")
def serve_admin():
    """Serve the admin console HTML page."""
    admin_path = FRONTEND_DIR / "admin.html"
    if admin_path.exists():
        return FileResponse(str(admin_path))
    return JSONResponse(
        status_code=404,
        content={"detail": "Admin console not found. Ensure frontend/admin.html exists."},
    )


# ---------------------------------------------------------------------------
# DATA API
# ---------------------------------------------------------------------------

@router.get("/api/stats")
def admin_stats():
    """Aggregate statistics for the dashboard overview."""
    return get_stats()


@router.get("/api/conversations")
def admin_conversations(limit: int = Query(50, ge=1, le=200)):
    """List recent conversations with summary info."""
    return get_conversations_summary(limit=limit)


@router.get("/api/conversations/{session_id}")
def admin_conversation_detail(session_id: str):
    """Get full transcript for a specific conversation."""
    events = get_conversation(session_id)
    if not events:
        return JSONResponse(
            status_code=404,
            content={"detail": f"No conversation found for session {session_id}"},
        )
    return events


@router.get("/api/events")
def admin_events(
    limit: int = Query(100, ge=1, le=500),
    event_type: str = Query(None, pattern="^(conversation_turn|query_execution|crisis_detected|session_reset)$"),
):
    """Get recent events, optionally filtered by type."""
    return get_recent_events(limit=limit, event_type=event_type)


@router.get("/api/queries")
def admin_queries(limit: int = Query(100, ge=1, le=500)):
    """Get recent query execution log."""
    return get_query_log(limit=limit)


@router.get("/api/eval")
def admin_eval():
    """Get LLM-as-judge evaluation results."""
    results = get_eval_results()
    if results is None:
        # Try loading from the default file location
        eval_path = TESTS_DIR / "eval_report.json"
        if eval_path.exists():
            load_eval_results_from_file(str(eval_path))
            results = get_eval_results()

    if results is None:
        # Return 200 with empty sentinel — 404 causes noisy server logs during polling
        return JSONResponse(
            status_code=200,
            content={"results": None, "detail": "No evaluation results yet. Use the Run Evals button to generate them."},
        )
    return results


@router.get("/api/eval/status")
def admin_eval_status():
    """Check whether an eval run is in progress."""
    with _eval_lock:
        return {"running": _eval_running, **_eval_status}


@router.post("/api/eval/run")
async def admin_eval_run(
    background_tasks: BackgroundTasks,
    scenarios: int = Query(None, ge=1, le=30, description="Max scenarios to run (default: all)"),
    category: str = Query(None, description="Only run scenarios in this category"),
):
    """Trigger an LLM-as-judge eval run in the background."""
    global _eval_running, _eval_status

    if _eval_running:
        return JSONResponse(
            status_code=409,
            content={"detail": "An eval run is already in progress."},
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=500,
            content={"detail": "ANTHROPIC_API_KEY is not set on the server."},
        )

    _eval_running = True
    _eval_status = {"started_at": datetime.now(timezone.utc).isoformat(), "message": "Starting…"}

    background_tasks.add_task(_run_eval_background, api_key, scenarios, category)

    return {"detail": "Eval started. Poll /admin/api/eval/status for progress."}


def _run_eval_background(api_key: str, max_scenarios: Optional[int], category: Optional[str]):
    """Run the eval suite in a background thread and store results."""
    global _eval_running, _eval_status

    try:
        # Ensure the backend package is importable from within the eval module
        backend_dir = str(TESTS_DIR.parent / "backend")
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        import importlib.util
        spec = importlib.util.spec_from_file_location("eval_llm_judge", str(TESTS_DIR / "eval_llm_judge.py"))
        eval_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eval_module)

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Select scenarios
        scenarios = eval_module.SCENARIOS
        if category:
            scenarios = [s for s in scenarios if s["category"] == category]
        if max_scenarios:
            scenarios = scenarios[:max_scenarios]

        total = len(scenarios)
        with _eval_lock:
            _eval_status["message"] = f"Running {total} scenario(s)…"
            _eval_status["total"] = total
            _eval_status["completed"] = 0

        results = []
        for i, scenario in enumerate(scenarios):
            with _eval_lock:
                _eval_status["message"] = f"[{i+1}/{total}] {scenario['name']}"
                _eval_status["completed"] = i

            conversation = eval_module.simulate_conversation(scenario, client)
            judgment = eval_module.judge_conversation(client, conversation)
            results.append({"conversation": conversation, "judgment": judgment})

        report = eval_module.generate_report(results)

        # Persist to file and memory
        out_path = TESTS_DIR / "eval_report.json"
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)

        set_eval_results(report)

        with _eval_lock:
            _eval_status = {
                "message": f"Done — {total} scenario(s) evaluated.",
                "completed": total,
                "total": total,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }

    except Exception as e:
        logger.exception("Eval run failed")
        with _eval_lock:
            _eval_status = {"message": f"Error: {e}"}
    finally:
        with _eval_lock:
            _eval_running = False
