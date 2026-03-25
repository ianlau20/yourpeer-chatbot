from copy import deepcopy
from typing import Dict


# In-memory only (demo)
# session_id -> slot dict
_SESSION_STATE: Dict[str, dict] = {}


def get_session_slots(session_id: str) -> dict:
    return deepcopy(_SESSION_STATE.get(session_id, {}))


def save_session_slots(session_id: str, slots: dict) -> None:
    _SESSION_STATE[session_id] = deepcopy(slots)