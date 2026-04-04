"""
Audit Log — Records anonymized conversation events for staff review.

Stores a capped ring buffer of conversation events in memory (demo mode).
All entries are already PII-redacted by the chatbot pipeline before
reaching this module.

Event types:
    - conversation_turn: A single user message + bot response pair
    - query_execution:   A database query that was executed
    - crisis_detected:   Crisis language was detected
    - session_reset:     User started over
    - feedback:          Thumbs up/down from the user after results

Production note: Replace the in-memory store with a persistent database
(PostgreSQL, Redis, etc.) for real deployments.
"""

import time
import threading
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

MAX_EVENTS = 2000          # Maximum events stored in memory
MAX_CONVERSATIONS = 500    # Maximum unique conversations tracked

# ---------------------------------------------------------------------------
# IN-MEMORY STORE
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# All events in insertion order (ring buffer)
_events: deque = deque(maxlen=MAX_EVENTS)

# Conversation index: session_id → list of event indices
_conversations: dict = {}

# Query execution log
_query_log: deque = deque(maxlen=MAX_EVENTS)

# Eval results (loaded from JSON file or set programmatically)
_eval_results: Optional[dict] = None


# ---------------------------------------------------------------------------
# EVENT RECORDING
# ---------------------------------------------------------------------------

def log_conversation_turn(
    session_id: str,
    user_message_redacted: str,
    bot_response: str,
    slots: dict,
    category: str,
    services_count: int = 0,
    quick_replies: list = None,
    follow_up_needed: bool = False,
):
    """Record a single conversation turn (user message + bot response)."""
    # Strip internal keys from slots for display
    clean_slots = {
        k: v for k, v in (slots or {}).items()
        if v is not None and not k.startswith("_") and k != "transcript"
    }

    event = {
        "type": "conversation_turn",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "user_message": user_message_redacted,
        "bot_response": bot_response,
        "category": category,
        "slots": clean_slots,
        "services_count": services_count,
        "quick_replies": [qr.get("label", qr) if isinstance(qr, dict) else qr
                          for qr in (quick_replies or [])],
        "follow_up_needed": follow_up_needed,
    }

    with _lock:
        _events.append(event)
        if session_id not in _conversations:
            _conversations[session_id] = []
            # Evict oldest conversations if over limit
            if len(_conversations) > MAX_CONVERSATIONS:
                oldest = next(iter(_conversations))
                del _conversations[oldest]
        _conversations[session_id].append(len(_events) - 1)


def log_query_execution(
    session_id: str,
    template_name: str,
    params: dict,
    result_count: int,
    relaxed: bool,
    execution_ms: int,
):
    """Record a database query execution."""
    event = {
        "type": "query_execution",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "template_name": template_name,
        "params": {k: v for k, v in params.items() if k != "max_results"},
        "result_count": result_count,
        "relaxed": relaxed,
        "execution_ms": execution_ms,
    }

    with _lock:
        _events.append(event)
        _query_log.append(event)


def log_crisis_detected(
    session_id: str,
    crisis_category: str,
    user_message_redacted: str,
):
    """Record a crisis detection event."""
    event = {
        "type": "crisis_detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "crisis_category": crisis_category,
        "user_message": user_message_redacted,
    }

    with _lock:
        _events.append(event)
        if session_id not in _conversations:
            _conversations[session_id] = []
        _conversations[session_id].append(len(_events) - 1)


def log_session_reset(session_id: str):
    """Record a session reset."""
    event = {
        "type": "session_reset",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
    }

    with _lock:
        _events.append(event)


def log_feedback(session_id: str, rating: str, comment: Optional[str] = None):
    """Record a thumbs up/down feedback event.

    Args:
        session_id: The session the feedback belongs to.
        rating: 'up' or 'down'.
        comment: Optional free-text comment (keep brief; no PII expected).
    """
    if rating not in ("up", "down"):
        raise ValueError(f"rating must be 'up' or 'down', got {rating!r}")

    event = {
        "type": "feedback",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "rating": rating,
        "comment": comment or None,
    }

    with _lock:
        _events.append(event)
        if session_id not in _conversations:
            _conversations[session_id] = []
        _conversations[session_id].append(len(_events) - 1)


# ---------------------------------------------------------------------------
# DATA RETRIEVAL (for the admin API)
# ---------------------------------------------------------------------------

def get_recent_events(limit: int = 100, event_type: str = None) -> list:
    """Get recent events, optionally filtered by type."""
    with _lock:
        events = list(_events)

    if event_type:
        events = [e for e in events if e["type"] == event_type]

    return events[-limit:]


def get_conversation(session_id: str) -> list:
    """Get all events for a specific conversation."""
    with _lock:
        events = list(_events)

    return [e for e in events if e.get("session_id") == session_id]


def get_conversations_summary(limit: int = 50) -> list:
    """Get a summary of recent conversations."""
    with _lock:
        events = list(_events)

    # Group by session_id
    sessions = {}
    for e in events:
        sid = e.get("session_id")
        if not sid:
            continue
        if sid not in sessions:
            sessions[sid] = {
                "session_id": sid,
                "first_seen": e["timestamp"],
                "last_seen": e["timestamp"],
                "turn_count": 0,
                "services_delivered": 0,
                "crisis_detected": False,
                "categories": set(),
                "final_slots": {},
            }
        s = sessions[sid]
        s["last_seen"] = e["timestamp"]

        if e["type"] == "conversation_turn":
            s["turn_count"] += 1
            s["services_delivered"] += e.get("services_count", 0)
            if e.get("category"):
                s["categories"].add(e["category"])
            if e.get("slots"):
                s["final_slots"] = e["slots"]
        elif e["type"] == "crisis_detected":
            s["crisis_detected"] = True
        elif e["type"] == "query_execution":
            s["services_delivered"] = max(
                s["services_delivered"], e.get("result_count", 0)
            )

    # Convert sets to lists for JSON serialization
    result = []
    for s in sessions.values():
        s["categories"] = sorted(s["categories"])
        result.append(s)

    # Sort by last_seen descending
    result.sort(key=lambda x: x["last_seen"], reverse=True)

    return result[:limit]


def get_query_log(limit: int = 100) -> list:
    """Get recent query execution log."""
    with _lock:
        return list(_query_log)[-limit:]


def get_stats() -> dict:
    """Get aggregate statistics for the dashboard."""
    with _lock:
        events = list(_events)

    total_turns = sum(1 for e in events if e["type"] == "conversation_turn")
    total_queries = sum(1 for e in events if e["type"] == "query_execution")
    total_crises = sum(1 for e in events if e["type"] == "crisis_detected")
    total_resets = sum(1 for e in events if e["type"] == "session_reset")
    feedback_up = sum(1 for e in events if e["type"] == "feedback" and e.get("rating") == "up")
    feedback_down = sum(1 for e in events if e["type"] == "feedback" and e.get("rating") == "down")

    unique_sessions = set(e.get("session_id") for e in events if e.get("session_id"))

    # Category distribution
    categories = {}
    for e in events:
        if e["type"] == "conversation_turn" and e.get("category"):
            cat = e["category"]
            categories[cat] = categories.get(cat, 0) + 1

    # Service type distribution
    service_types = {}
    for e in events:
        if e["type"] == "conversation_turn":
            st = e.get("slots", {}).get("service_type")
            if st:
                service_types[st] = service_types.get(st, 0) + 1

    # Relaxed query rate
    relaxed_count = sum(
        1 for e in events
        if e["type"] == "query_execution" and e.get("relaxed")
    )

    return {
        "total_events": len(events),
        "total_turns": total_turns,
        "total_queries": total_queries,
        "total_crises": total_crises,
        "total_resets": total_resets,
        "unique_sessions": len(unique_sessions),
        "feedback_up": feedback_up,
        "feedback_down": feedback_down,
        "feedback_score": (
            round(feedback_up / (feedback_up + feedback_down), 2)
            if (feedback_up + feedback_down) > 0 else None
        ),
        "category_distribution": categories,
        "service_type_distribution": service_types,
        "relaxed_query_rate": (
            round(relaxed_count / total_queries, 2) if total_queries else 0
        ),
    }


# ---------------------------------------------------------------------------
# EVAL RESULTS
# ---------------------------------------------------------------------------

def set_eval_results(results: dict):
    """Store eval results for the admin console."""
    global _eval_results
    _eval_results = deepcopy(results)


def get_eval_results() -> Optional[dict]:
    """Get stored eval results."""
    return deepcopy(_eval_results) if _eval_results else None


def load_eval_results_from_file(path: str):
    """Load eval results from a JSON file."""
    import json
    try:
        with open(path) as f:
            data = json.load(f)
        set_eval_results(data)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLEAR (for testing)
# ---------------------------------------------------------------------------

def clear_audit_log():
    """Clear all audit data. Used in tests."""
    global _eval_results
    with _lock:
        _events.clear()
        _conversations.clear()
        _query_log.clear()
    _eval_results = None
