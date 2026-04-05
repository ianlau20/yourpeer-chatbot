import hmac
import hashlib
import os
import secrets

# Set SESSION_SECRET in your environment. Never commit a real value.
_SECRET = os.environ.get("SESSION_SECRET", "").encode()

def generate_session_id() -> str:
    """Create a new cryptographically random session ID and sign it."""
    raw = secrets.token_urlsafe(32)
    return _sign(raw)

def validate_session_id(token: str) -> bool:
    """Return True only if this token was issued by us."""
    if not _SECRET:
        # No secret configured — fail closed in production, warn loudly
        raise RuntimeError("SESSION_SECRET env var is not set")
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = _make_sig(raw)
    return hmac.compare_digest(expected, sig)

def _sign(raw: str) -> str:
    return f"{raw}.{_make_sig(raw)}"

def _make_sig(raw: str) -> str:
    return hmac.new(_SECRET, raw.encode(), hashlib.sha256).hexdigest()