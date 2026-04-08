"""Stub audit log for testing — stores events in memory."""

_events = []

def log_conversation_turn(**kwargs):
    _events.append(kwargs)

def log_query_execution(**kwargs):
    _events.append(kwargs)

def log_crisis_detected(*args, **kwargs):
    _events.append({"type": "crisis", **kwargs})

def log_session_reset(*args, **kwargs):
    _events.append({"type": "reset", **kwargs})

def log_feedback(**kwargs):
    _events.append({"type": "feedback", **kwargs})

def get_recent_events(n=10):
    """Return the most recent n events."""
    return list(reversed(_events[-n:]))

def clear_audit_log():
    """Clear all stored events."""
    _events.clear()
