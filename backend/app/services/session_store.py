import time
from copy import deepcopy
from typing import Dict, Tuple


# In-memory only (demo).
# session_id -> (slot_dict, last_accessed_timestamp)
_SESSION_STATE: Dict[str, Tuple[dict, float]] = {}

# Sessions expire after 30 minutes of inactivity.
SESSION_TTL_SECONDS = 30 * 60

# Maximum number of sessions to keep in memory.
# If exceeded, the oldest sessions are evicted.
MAX_SESSIONS = 500


def get_session_slots(session_id: str) -> dict:
    _evict_expired()
    entry = _SESSION_STATE.get(session_id)
    if entry is None:
        return {}
    slots, _ = entry
    # Update last-accessed time
    _SESSION_STATE[session_id] = (slots, time.monotonic())
    return deepcopy(slots)


def save_session_slots(session_id: str, slots: dict) -> None:
    _evict_expired()
    _SESSION_STATE[session_id] = (deepcopy(slots), time.monotonic())

    # Hard cap: if we're over the limit, drop the oldest sessions
    if len(_SESSION_STATE) > MAX_SESSIONS:
        sorted_keys = sorted(
            _SESSION_STATE.keys(),
            key=lambda k: _SESSION_STATE[k][1],
        )
        # Remove the oldest 10% to avoid evicting on every request
        to_remove = max(1, len(sorted_keys) // 10)
        for key in sorted_keys[:to_remove]:
            del _SESSION_STATE[key]


def _evict_expired() -> None:
    """Remove sessions that haven't been accessed within the TTL."""
    now = time.monotonic()
    expired = [
        sid for sid, (_, last_accessed) in _SESSION_STATE.items()
        if now - last_accessed > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _SESSION_STATE[sid]


def clear_session(session_id: str) -> None:
    """Remove all slot data for a session (used for 'start over')."""
    _SESSION_STATE.pop(session_id, None)
