"""
Session Store — in-memory session state with optional SQLite persistence.

When PILOT_DB_PATH is set, sessions are written through to SQLite so they
survive server restarts. On startup, call hydrate_from_db() to reload.
"""

import time
import threading
from copy import deepcopy
from typing import Dict, Tuple

from app.services import persistence

# In-memory store.
# session_id -> (slot_dict, last_accessed_timestamp)
_SESSION_STATE: Dict[str, Tuple[dict, float]] = {}

# Sessions expire after 30 minutes of inactivity.
SESSION_TTL_SECONDS = 30 * 60

# Maximum number of sessions to keep in memory.
MAX_SESSIONS = 500

_lock = threading.Lock()


def get_session_slots(session_id: str) -> dict:
    with _lock:
        _evict_expired()
        entry = _SESSION_STATE.get(session_id)
        if entry is None:
            return {}
        slots, _ = entry
        now = time.monotonic()
        _SESSION_STATE[session_id] = (slots, now)
        persistence.persist_session(session_id, slots, now)
        return deepcopy(slots)


def save_session_slots(session_id: str, slots: dict) -> None:
    with _lock:
        _evict_expired()
        now = time.monotonic()
        _SESSION_STATE[session_id] = (deepcopy(slots), now)

        if len(_SESSION_STATE) > MAX_SESSIONS:
            sorted_keys = sorted(
                _SESSION_STATE.keys(),
                key=lambda k: _SESSION_STATE[k][1],
            )
            to_remove = max(1, len(sorted_keys) // 10)
            for key in sorted_keys[:to_remove]:
                del _SESSION_STATE[key]
                persistence.delete_session(key)
    persistence.persist_session(session_id, slots, time.monotonic())


def _evict_expired() -> None:
    """Remove sessions that haven't been accessed within the TTL.
    MUST be called with _lock held.
    """
    now = time.monotonic()
    expired = [
        sid for sid, (_, last_accessed) in _SESSION_STATE.items()
        if now - last_accessed > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _SESSION_STATE[sid]
        persistence.delete_session(sid)


def session_exists(session_id: str) -> bool:
    """Check whether a session exists and is not expired."""
    with _lock:
        _evict_expired()
        return session_id in _SESSION_STATE


def clear_session(session_id: str) -> None:
    """Remove all slot data for a session (used for 'start over')."""
    with _lock:
        _SESSION_STATE.pop(session_id, None)
    persistence.delete_session(session_id)


# ---------------------------------------------------------------------------
# HYDRATION — load persisted sessions on startup
# ---------------------------------------------------------------------------

def hydrate_from_db() -> int:
    """Load persisted sessions from SQLite into in-memory store.

    Returns the number of sessions loaded. Call once at startup.
    """
    if not persistence.is_enabled():
        return 0

    sessions = persistence.load_all_sessions(SESSION_TTL_SECONDS)
    if not sessions:
        return 0

    with _lock:
        for session_id, (slots, last_accessed) in sessions.items():
            if len(_SESSION_STATE) >= MAX_SESSIONS:
                break
            _SESSION_STATE[session_id] = (slots, last_accessed)

    from app.services.persistence import logger
    logger.info(f"Hydrated session store from SQLite: {len(sessions)} sessions")
    return len(sessions)
