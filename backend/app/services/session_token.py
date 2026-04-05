import hmac
import hashlib
import logging
import os
import secrets

logger = logging.getLogger(__name__)

# Set SESSION_SECRET in your environment. Never commit a real value.
_SECRET = os.environ.get("SESSION_SECRET", "").encode()

if not _SECRET:
    logger.warning(
        "SESSION_SECRET is not set — session tokens will not be signed. "
        "This is fine for local development but MUST be set in production."
    )


def generate_session_id() -> str:
    """Create a new cryptographically random session ID.

    When SESSION_SECRET is set, the ID is HMAC-signed so the server can
    verify it was issued by us. When unset (local dev), returns an
    unsigned random token.
    """
    raw = secrets.token_urlsafe(32)
    if _SECRET:
        return _sign(raw)
    return raw


def validate_session_id(token: str) -> bool:
    """Return True if this token was issued by us.

    When SESSION_SECRET is not set (local dev), all tokens are accepted.
    When set, the HMAC signature is verified.
    """
    if not _SECRET:
        # No secret configured — open access (dev mode), matching the
        # pattern used by require_admin_key in dependencies.py
        return True
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    expected = _make_sig(raw)
    return hmac.compare_digest(expected, sig)


def _sign(raw: str) -> str:
    return f"{raw}.{_make_sig(raw)}"


def _make_sig(raw: str) -> str:
    return hmac.HMAC(_SECRET, raw.encode(), hashlib.sha256).hexdigest()
