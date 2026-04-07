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
    request_id: Optional[str] = None,
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
        "request_id": request_id,
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
    freshness: Optional[dict] = None,
    request_id: Optional[str] = None,
):
    """Record a database query execution."""
    event = {
        "type": "query_execution",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "request_id": request_id,
        "template_name": template_name,
        "params": {k: v for k, v in params.items() if k != "max_results"},
        "result_count": result_count,
        "relaxed": relaxed,
        "execution_ms": execution_ms,
        "freshness": freshness,
    }

    with _lock:
        _events.append(event)
        _query_log.append(event)


def log_crisis_detected(
    session_id: str,
    crisis_category: str,
    user_message_redacted: str,
    request_id: Optional[str] = None,
):
    """Record a crisis detection event."""
    event = {
        "type": "crisis_detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "request_id": request_id,
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

    # --- Per-session category sets (used for several metrics below) ---
    # Maps session_id → set of categories seen in that session's turns.
    session_categories: dict[str, set] = {}
    for e in events:
        if e["type"] == "conversation_turn" and e.get("session_id"):
            sid = e["session_id"]
            cat = e.get("category")
            if cat:
                session_categories.setdefault(sid, set()).add(cat)

    # Fix #1: Escalation count — sessions where user asked for a person.
    total_escalations = sum(
        1 for cats in session_categories.values()
        if "escalation" in cats
    )

    # Fix #2: Service-intent sessions — denominator for task completion.
    # A session has "service intent" if any turn was categorized as a
    # service request or reached the confirmation stage.
    _SERVICE_INTENT_CATEGORIES = {
        "service", "confirmation", "confirmation_nudge",
        "confirm_yes", "confirm_change_service",
        "confirm_change_location", "confirm_deny",
    }
    service_intent_sessions = sum(
        1 for cats in session_categories.values()
        if cats & _SERVICE_INTENT_CATEGORIES
    )

    # Fix #3: Confirmation-stage sessions and breakdown.
    # A session "reached confirmation" if any turn has a confirmation-
    # stage category.
    _CONFIRMATION_CATEGORIES = {
        "confirmation", "confirmation_nudge",
        "confirm_yes", "confirm_change_service",
        "confirm_change_location", "confirm_deny",
    }
    sessions_at_confirmation = sum(
        1 for cats in session_categories.values()
        if cats & _CONFIRMATION_CATEGORIES
    )

    # Confirmation action counts (across all turns, not per-session)
    confirm_yes_count = categories.get("confirm_yes", 0)
    confirm_change_service_count = categories.get("confirm_change_service", 0)
    confirm_change_location_count = categories.get("confirm_change_location", 0)
    confirm_deny_count = categories.get("confirm_deny", 0)
    total_confirm_actions = (
        confirm_yes_count + confirm_change_service_count
        + confirm_change_location_count + confirm_deny_count
    )

    # Fix #4: Slot correction rate — sessions where user changed a slot
    # after reaching confirmation, as a % of sessions that reached
    # confirmation at all.
    sessions_with_correction = sum(
        1 for cats in session_categories.values()
        if cats & {"confirm_change_service", "confirm_change_location"}
    )

    # Sessions that reached confirmation but never confirmed (abandoned)
    sessions_abandoned_at_confirm = sum(
        1 for cats in session_categories.values()
        if cats & _CONFIRMATION_CATEGORIES and "confirm_yes" not in cats
    )

    # Slot confirmation rate: of sessions that executed a query, how many
    # went through the explicit confirmation step first?  Should be ~100%
    # by design — any gap means the confirmation flow was bypassed.
    sessions_with_query = {
        e["session_id"] for e in events
        if e["type"] == "query_execution" and e.get("session_id")
    }
    sessions_with_confirmed_query = sum(
        1 for sid in sessions_with_query
        if sid in session_categories and "confirm_yes" in session_categories[sid]
    )

    # Data freshness: aggregate last_validated_at stats across all queries.
    total_cards_served = 0
    total_cards_with_date = 0
    total_cards_fresh = 0
    for e in events:
        if e["type"] == "query_execution":
            f = e.get("freshness")
            if f:
                total_cards_served += f.get("total", 0)
                total_cards_with_date += f.get("total_with_date", 0)
                total_cards_fresh += f.get("fresh", 0)

    # --- Conversation quality metrics ---

    # Sessions with at least one emotional turn
    sessions_with_emotional = sum(
        1 for cats in session_categories.values()
        if "emotional" in cats
    )

    # Of those, how many subsequently escalated to a peer navigator?
    emotional_then_escalation = sum(
        1 for cats in session_categories.values()
        if "emotional" in cats and "escalation" in cats
    )

    # Of those, how many eventually reached a service search?
    emotional_then_service = sum(
        1 for sid, cats in session_categories.items()
        if "emotional" in cats and (
            cats & _SERVICE_INTENT_CATEGORIES or sid in sessions_with_query
        )
    )

    # Bot question turn count (not per-session — per-turn)
    bot_question_turns = categories.get("bot_question", 0)

    # Sessions with a bot question followed by frustration
    sessions_with_bot_question = sum(
        1 for cats in session_categories.values()
        if "bot_question" in cats
    )
    bot_question_then_frustration = sum(
        1 for cats in session_categories.values()
        if "bot_question" in cats and "frustration" in cats
    )

    # Sessions that reached query_execution via conversation (had a general
    # or emotional turn) vs. pure button-tap flows (only service/confirm turns)
    _CONVERSATIONAL_CATEGORIES = {"general", "emotional", "confused", "greeting"}
    conversational_discovery = sum(
        1 for sid in sessions_with_query
        if sid in session_categories
        and session_categories[sid] & _CONVERSATIONAL_CATEGORIES
    )

    return {
        "total_events": len(events),
        "total_turns": total_turns,
        "total_queries": total_queries,
        "total_crises": total_crises,
        "total_resets": total_resets,
        "total_escalations": total_escalations,
        "unique_sessions": len(unique_sessions),
        "service_intent_sessions": service_intent_sessions,
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
        "slot_confirmation_rate": (
            round(sessions_with_confirmed_query / len(sessions_with_query), 2)
            if sessions_with_query else None
        ),
        "slot_correction_rate": (
            round(sessions_with_correction / sessions_at_confirmation, 2)
            if sessions_at_confirmation > 0 else None
        ),
        "data_freshness_rate": (
            round(total_cards_fresh / total_cards_served, 2)
            if total_cards_served > 0 else None
        ),
        "data_freshness_detail": {
            "cards_served": total_cards_served,
            "cards_with_date": total_cards_with_date,
            "cards_fresh": total_cards_fresh,
        },
        "conversation_quality": {
            "emotional_sessions": sessions_with_emotional,
            "emotional_rate": (
                round(sessions_with_emotional / len(unique_sessions), 2)
                if unique_sessions else None
            ),
            "emotional_to_escalation": (
                round(emotional_then_escalation / sessions_with_emotional, 2)
                if sessions_with_emotional > 0 else None
            ),
            "emotional_to_service": (
                round(emotional_then_service / sessions_with_emotional, 2)
                if sessions_with_emotional > 0 else None
            ),
            "bot_question_turns": bot_question_turns,
            "bot_question_rate": (
                round(bot_question_turns / total_turns, 2)
                if total_turns > 0 else None
            ),
            "bot_question_sessions": sessions_with_bot_question,
            "bot_question_to_frustration": (
                round(bot_question_then_frustration / sessions_with_bot_question, 2)
                if sessions_with_bot_question > 0 else None
            ),
            "conversational_discovery": conversational_discovery,
            "conversational_discovery_rate": (
                round(conversational_discovery / len(sessions_with_query), 2)
                if sessions_with_query else None
            ),
        },
        "confirmation_breakdown": {
            "confirm": confirm_yes_count,
            "change_service": confirm_change_service_count,
            "change_location": confirm_change_location_count,
            "deny": confirm_deny_count,
            "total_actions": total_confirm_actions,
            "confirm_rate": (
                round(confirm_yes_count / total_confirm_actions, 2)
                if total_confirm_actions > 0 else None
            ),
            "sessions_at_confirmation": sessions_at_confirmation,
            "sessions_abandoned": sessions_abandoned_at_confirm,
            "abandon_rate": (
                round(sessions_abandoned_at_confirm / sessions_at_confirmation, 2)
                if sessions_at_confirmation > 0 else None
            ),
        },
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
