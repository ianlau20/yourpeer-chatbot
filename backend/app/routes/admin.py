"""
Admin API Routes — Staff review console endpoints.

All endpoints are prefixed with /admin/api/.
The admin HTML page is served at /admin/.
"""

import os
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse

from app.services.audit_log import (
    get_recent_events,
    get_conversation,
    get_conversations_summary,
    get_query_log,
    get_stats,
    get_eval_results,
    load_eval_results_from_file,
)

router = APIRouter(prefix="/admin", tags=["admin"])

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
        eval_path = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "eval_report.json"
        if eval_path.exists():
            load_eval_results_from_file(str(eval_path))
            results = get_eval_results()

    if results is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": "No evaluation results found. Run: "
                "ANTHROPIC_API_KEY=sk-... python tests/eval_llm_judge.py --output tests/eval_report.json"
            },
        )
    return results
