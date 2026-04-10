"""
Audit Log — event store for the staff review console.

Stores conversation turns, query executions, crisis events, session resets,
and user feedback in ring buffers. Provides aggregation functions for the
admin dashboard (stats, conversation summaries, query log).

Primary storage is in-memory for fast reads. When PILOT_DB_PATH is set,
events are also written to SQLite for persistence across server restarts.
On startup, call hydrate_from_db() to reload persisted data.

Thread-safe: all mutations and reads acquire _lock. FastAPI serves
concurrent requests, so unguarded dict/deque mutations would corrupt state.
"""

import json
import logging
import threading
from collections import deque, OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from app.services import persistence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

MAX_EVENTS = 2000
MAX_CONVERSATIONS = 500

# ---------------------------------------------------------------------------
# STORAGE
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_events: deque = deque(maxlen=MAX_EVENTS)
_conversations: OrderedDict = OrderedDict()
_query_log: deque = deque(maxlen=MAX_EVENTS)
_eval_results: Optional[dict] = None


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_slots(slots: Optional[dict]) -> dict:
    if not slots:
        return {}
    return {
        k: v for k, v in slots.items()
        if v is not None and not k.startswith("_") and k != "transcript"
    }


def _extract_qr_labels(quick_replies: Optional[list]) -> list:
    if not quick_replies:
        return []
    return [qr["label"] if isinstance(qr, dict) else qr for qr in quick_replies]


def _register_conversation(session_id: str, event: dict) -> None:
    """MUST be called with _lock held."""
    if session_id not in _conversations:
        if len(_conversations) >= MAX_CONVERSATIONS:
            _conversations.popitem(last=False)
        _conversations[session_id] = []
    else:
        _conversations.move_to_end(session_id)
    _conversations[session_id].append(event)


# ---------------------------------------------------------------------------
# LOGGING FUNCTIONS
# ---------------------------------------------------------------------------

def log_conversation_turn(
    session_id="", user_message_redacted="", bot_response="",
    slots=None, category="", services_count=0, quick_replies=None,
    follow_up_needed=False, request_id=None, tone=None, **kwargs,
):
    event = {
        "type": "conversation_turn",
        "timestamp": _now_iso(),
        "session_id": session_id,
        "user_message": user_message_redacted,
        "bot_response": bot_response,
        "slots": _clean_slots(slots),
        "category": category,
        "services_count": services_count,
        "quick_replies": _extract_qr_labels(quick_replies),
        "follow_up_needed": follow_up_needed,
        "request_id": request_id,
        "tone": tone,
    }
    with _lock:
        _events.append(event)
        _register_conversation(session_id, event)
    persistence.persist_event(event)


def log_query_execution(
    session_id="", template_name="", params=None, result_count=0,
    relaxed=False, execution_ms=0, freshness=None, request_id=None,
    **kwargs,
):
    clean_params = dict(params or {})
    clean_params.pop("max_results", None)
    event = {
        "type": "query_execution",
        "timestamp": _now_iso(),
        "session_id": session_id,
        "template_name": template_name,
        "params": clean_params,
        "result_count": result_count,
        "relaxed": relaxed,
        "execution_ms": execution_ms,
        "freshness": freshness,
        "request_id": request_id,
    }
    with _lock:
        _events.append(event)
        _query_log.append(event)
        _register_conversation(session_id, event)
    persistence.persist_event(event)


def log_crisis_detected(
    session_id="", crisis_category="", user_message_redacted="",
    request_id=None, **kwargs,
):
    event = {
        "type": "crisis_detected",
        "timestamp": _now_iso(),
        "session_id": session_id,
        "crisis_category": crisis_category,
        "user_message": user_message_redacted,
        "request_id": request_id,
    }
    with _lock:
        _events.append(event)
        _register_conversation(session_id, event)
    persistence.persist_event(event)


def log_session_reset(session_id="", **kwargs):
    event = {
        "type": "session_reset",
        "timestamp": _now_iso(),
        "session_id": session_id,
    }
    with _lock:
        _events.append(event)
        _register_conversation(session_id, event)
    persistence.persist_event(event)


def log_feedback(session_id="", rating="", comment=None, **kwargs):
    event = {
        "type": "feedback",
        "timestamp": _now_iso(),
        "session_id": session_id,
        "rating": rating,
        "comment": comment,
    }
    with _lock:
        _events.append(event)
        _register_conversation(session_id, event)
    persistence.persist_event(event)


# ---------------------------------------------------------------------------
# RETRIEVAL
# ---------------------------------------------------------------------------

def get_recent_events(limit=100, event_type=None, n=None, **kwargs):
    if n is not None:
        limit = n
    with _lock:
        if event_type:
            filtered = [e for e in _events if e.get("type") == event_type]
            return list(filtered[-limit:])
        return list(list(_events)[-limit:])


def get_conversation(session_id: str) -> list:
    with _lock:
        return list(_conversations.get(session_id, []))


def get_conversations_summary(limit=50) -> list:
    with _lock:
        summaries = []
        for session_id in reversed(_conversations):
            events = _conversations[session_id]
            if not events:
                continue
            turns = [e for e in events if e.get("type") == "conversation_turn"]
            crisis = any(e.get("type") == "crisis_detected" for e in events)
            categories = list({t.get("category", "") for t in turns if t.get("category")})
            last_turn = turns[-1] if turns else {}
            summaries.append({
                "session_id": session_id,
                "turn_count": len(turns),
                "services_delivered": last_turn.get("services_count", 0),
                "crisis_detected": crisis,
                "categories": categories,
                "final_slots": last_turn.get("slots", {}),
                "last_seen": events[-1].get("timestamp", ""),
            })
            if len(summaries) >= limit:
                break
        return summaries


def get_query_log(limit=100) -> list:
    with _lock:
        return list(list(_query_log)[-limit:])


def get_stats() -> dict:
    with _lock:
        all_events = list(_events)

    turns = [e for e in all_events if e.get("type") == "conversation_turn"]
    queries = [e for e in all_events if e.get("type") == "query_execution"]
    crises = [e for e in all_events if e.get("type") == "crisis_detected"]
    resets = [e for e in all_events if e.get("type") == "session_reset"]
    feedbacks = [e for e in all_events if e.get("type") == "feedback"]

    all_sessions = {e.get("session_id") for e in all_events if e.get("session_id")}

    # Per-session categories
    sess_cats: dict[str, set] = {}
    for t in turns:
        sid = t.get("session_id", "")
        sess_cats.setdefault(sid, set()).add(t.get("category", ""))

    # Distributions
    cat_dist: dict[str, int] = {}
    svc_dist: dict[str, int] = {}
    for t in turns:
        cat = t.get("category", "general")
        cat_dist[cat] = cat_dist.get(cat, 0) + 1
        stype = t.get("slots", {}).get("service_type")
        if stype:
            svc_dist[stype] = svc_dist.get(stype, 0) + 1

    # Relaxed rate
    relaxed_rate = sum(1 for q in queries if q.get("relaxed")) / len(queries) if queries else 0

    # Escalations
    esc_sessions = {sid for sid, cats in sess_cats.items() if "escalation" in cats}

    # Service intent
    _svc = {"service", "confirmation", "confirm_yes", "confirm_change_service", "confirm_change_location"}
    svc_intent = {sid for sid, cats in sess_cats.items() if cats & _svc}

    # Slot correction rate
    at_conf = {sid for sid, cats in sess_cats.items() if "confirmation" in cats or "confirm_yes" in cats}
    with_corr = {sid for sid, cats in sess_cats.items() if "confirm_change_service" in cats or "confirm_change_location" in cats}
    slot_corr_rate = round(len(with_corr) / len(at_conf), 2) if at_conf else None

    # Slot confirmation rate
    q_sessions = {q.get("session_id") for q in queries if q.get("session_id")}
    confirmed_q = {sid for sid in q_sessions if sid in sess_cats and "confirm_yes" in sess_cats[sid]}
    slot_conf_rate = round(len(confirmed_q) / len(q_sessions), 2) if q_sessions else None

    # Confirmation breakdown
    ca = [t for t in turns if t.get("category", "").startswith("confirm_")]
    cb_yes = sum(1 for t in ca if t["category"] == "confirm_yes")
    cb_cl = sum(1 for t in ca if t["category"] == "confirm_change_location")
    cb_cs = sum(1 for t in ca if t["category"] == "confirm_change_service")
    cb_deny = sum(1 for t in ca if t["category"] == "confirm_deny")
    cb_total = len(ca)
    sess_at_c = {sid for sid, cats in sess_cats.items()
                 if "confirmation" in cats or any(c.startswith("confirm_") for c in cats)}
    sess_confirmed = {sid for sid, cats in sess_cats.items() if "confirm_yes" in cats}
    sess_abandoned = sess_at_c - sess_confirmed

    # Freshness
    cards_served = 0
    cards_fresh = 0
    for q in queries:
        f = q.get("freshness")
        if f and isinstance(f, dict) and f.get("total", 0) > 0:
            cards_served += f["total"]
            cards_fresh += f.get("fresh", 0)

    # Feedback
    fb_up = sum(1 for f in feedbacks if f.get("rating") == "up")
    fb_down = sum(1 for f in feedbacks if f.get("rating") == "down")
    fb_total = fb_up + fb_down

    cq = _conversation_quality(turns, queries, sess_cats)
    routing = _compute_routing(turns, cat_dist)
    tone_dist = _compute_tone_distribution(turns)
    multi = _compute_multi_intent(turns, queries, sess_cats)

    return {
        "total_events": len(all_events),
        "total_turns": len(turns),
        "total_queries": len(queries),
        "total_crises": len(crises),
        "total_resets": len(resets),
        "unique_sessions": len(all_sessions),
        "total_escalations": len(esc_sessions),
        "service_intent_sessions": len(svc_intent),
        "category_distribution": cat_dist,
        "service_type_distribution": svc_dist,
        "relaxed_query_rate": relaxed_rate,
        "slot_correction_rate": slot_corr_rate,
        "slot_confirmation_rate": slot_conf_rate,
        "confirmation_breakdown": {
            "confirm": cb_yes, "change_location": cb_cl, "change_service": cb_cs,
            "deny": cb_deny, "total_actions": cb_total,
            "confirm_rate": round(cb_yes / cb_total, 2) if cb_total else None,
            "sessions_at_confirmation": len(sess_at_c),
            "sessions_abandoned": len(sess_abandoned),
            "abandon_rate": round(len(sess_abandoned) / len(sess_at_c), 2) if sess_at_c else None,
        },
        "data_freshness_rate": round(cards_fresh / cards_served, 2) if cards_served else None,
        "data_freshness_detail": {"cards_served": cards_served, "cards_fresh": cards_fresh},
        "feedback_up": fb_up,
        "feedback_down": fb_down,
        "feedback_score": round(fb_up / fb_total, 2) if fb_total else None,
        "conversation_quality": cq,
        "routing": routing,
        "tone_distribution": tone_dist,
        "multi_intent": multi,
    }


def _conversation_quality(turns, queries, sess_cats):
    total_sess = len(sess_cats)
    total_turns = len(turns)

    emo = {sid for sid, cats in sess_cats.items() if "emotional" in cats}
    emo_rate = round(len(emo) / total_sess, 2) if total_sess else None
    emo_esc = (round(len({s for s in emo if "escalation" in sess_cats.get(s, set())}) / len(emo), 2)
               if emo else None)
    _s = {"service", "confirm_yes"}
    emo_svc = (round(len({s for s in emo if sess_cats.get(s, set()) & _s}) / len(emo), 2)
               if emo else None)

    bq_turns = sum(1 for t in turns if t.get("category") == "bot_question")
    bq_sess = {sid for sid, cats in sess_cats.items() if "bot_question" in cats}
    bq_rate = round(bq_turns / total_turns, 2) if total_turns else None
    bq_frust = (round(len({s for s in bq_sess if "frustration" in sess_cats.get(s, set())}) / len(bq_sess), 2)
                if bq_sess else None)

    q_sess = {q.get("session_id") for q in queries if q.get("session_id")}
    _conv = {"greeting", "emotional", "confused", "general", "bot_question"}
    conv_disc = {sid for sid in q_sess if sess_cats.get(sid, set()) & _conv}
    conv_rate = round(len(conv_disc) / len(q_sess), 2) if q_sess else None

    return {
        "emotional_sessions": len(emo), "emotional_rate": emo_rate,
        "emotional_to_escalation": emo_esc, "emotional_to_service": emo_svc,
        "bot_question_turns": bq_turns, "bot_question_rate": bq_rate,
        "bot_question_sessions": len(bq_sess), "bot_question_to_frustration": bq_frust,
        "conversational_discovery": len(conv_disc), "conversational_discovery_rate": conv_rate,
    }


# Routing bucket definitions — which categories map to which bucket.
_ROUTING_SERVICE_FLOW = {
    "service", "confirmation", "confirmation_nudge", "unrecognized_service",
    "confirm_yes", "confirm_deny", "confirm_change_service", "confirm_change_location",
    "queue_decline",
}
_ROUTING_CONVERSATIONAL = {
    "greeting", "thanks", "help", "bot_question", "bot_identity", "reset",
    "post_results",
}
_ROUTING_EMOTIONAL = {"emotional", "frustration", "confused"}
_ROUTING_SAFETY = {"crisis", "escalation"}
_ROUTING_GENERAL = {"general"}


def _compute_routing(turns: list, cat_dist: dict) -> dict:
    """Compute routing distribution: how turns are bucketed across handlers."""
    total = len(turns)

    buckets = {
        "service_flow": 0,
        "conversational": 0,
        "emotional": 0,
        "safety": 0,
        "general": 0,
    }
    for t in turns:
        cat = t.get("category", "general")
        if cat in _ROUTING_SERVICE_FLOW:
            buckets["service_flow"] += 1
        elif cat in _ROUTING_CONVERSATIONAL:
            buckets["conversational"] += 1
        elif cat in _ROUTING_EMOTIONAL:
            buckets["emotional"] += 1
        elif cat in _ROUTING_SAFETY:
            buckets["safety"] += 1
        else:
            buckets["general"] += 1

    general_rate = round(buckets["general"] / total, 2) if total else None

    return {
        "total_categorized": total,
        "buckets": buckets,
        "general_rate": general_rate,
        "category_distribution": cat_dist,
    }


def _compute_tone_distribution(turns: list) -> dict:
    """Compute tone distribution across all turns."""
    tones: dict[str, int] = {}
    total_with_tone = 0
    turns_without_tone = 0

    for t in turns:
        tone = t.get("tone")
        if tone and tone != "crisis":
            # "crisis" is a routing category, not a tone for display purposes.
            # The tone distribution tracks emotional modifiers:
            # emotional, frustrated, confused, urgent.
            tones[tone] = tones.get(tone, 0) + 1
            total_with_tone += 1
        else:
            turns_without_tone += 1

    return {
        "tones": tones,
        "total_with_tone": total_with_tone,
        "turns_without_tone": turns_without_tone,
    }


def _compute_multi_intent(turns: list, queries: list, sess_cats: dict) -> dict:
    """Compute multi-intent queue metrics.

    Queue offers: sessions where 2+ different query templates were executed
                  OR a queue_decline event occurred (an offer was made).
    Queue declines: turns with category 'queue_decline'.
    """
    # Count explicit queue declines
    queue_declines = sum(1 for t in turns if t.get("category") == "queue_decline")

    # Sessions with queue declines
    decline_sessions = {
        t.get("session_id") for t in turns
        if t.get("category") == "queue_decline"
    }

    # Sessions with 2+ query executions (user accepted at least one queue offer)
    session_queries: dict[str, set] = {}
    for q in queries:
        sid = q.get("session_id", "")
        template = q.get("template_name", "")
        session_queries.setdefault(sid, set()).add(template)

    multi_query_sessions = {
        sid for sid, templates in session_queries.items()
        if len(templates) >= 2
    }

    # Queue offers = sessions with decline + sessions with multiple queries
    queue_offer_sessions = decline_sessions | multi_query_sessions
    queue_offers = len(queue_offer_sessions)

    return {
        "queue_offers": queue_offers,
        "queue_declines": queue_declines,
        "queue_accept_sessions": len(multi_query_sessions),
    }


# ---------------------------------------------------------------------------
# EVAL RESULTS
# ---------------------------------------------------------------------------

def set_eval_results(data: dict) -> None:
    global _eval_results
    with _lock:
        _eval_results = deepcopy(data)
    persistence.persist_eval_results(data)


def get_eval_results() -> Optional[dict]:
    with _lock:
        return deepcopy(_eval_results) if _eval_results is not None else None


def load_eval_results_from_file(path: str) -> bool:
    try:
        with open(path) as f:
            data = json.load(f)
        set_eval_results(data)
        return True
    except Exception as e:
        logger.error(f"Failed to load eval results from {path}: {e}")
        return False


# ---------------------------------------------------------------------------
# CLEAR
# ---------------------------------------------------------------------------

def clear_audit_log() -> None:
    global _eval_results
    with _lock:
        _events.clear()
        _conversations.clear()
        _query_log.clear()
        _eval_results = None
    persistence.clear_events()


# ---------------------------------------------------------------------------
# HYDRATION — load persisted data on startup
# ---------------------------------------------------------------------------

def hydrate_from_db() -> int:
    """Load persisted events from SQLite into in-memory stores.

    Returns the number of events loaded. Call once at startup.
    """
    if not persistence.is_enabled():
        return 0

    events = persistence.load_all_events(MAX_EVENTS)
    if not events:
        return 0

    with _lock:
        for event in events:
            _events.append(event)
            sid = event.get("session_id", "")
            if sid:
                _register_conversation(sid, event)
            if event.get("type") == "query_execution":
                _query_log.append(event)

    # Also load eval results
    eval_data = persistence.load_eval_results()
    if eval_data:
        global _eval_results
        with _lock:
            _eval_results = eval_data

    logger.info(f"Hydrated audit log from SQLite: {len(events)} events")
    return len(events)
