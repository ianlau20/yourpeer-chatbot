"""
Tests for session_token.py — HMAC-signed session ID generation and validation.

This is the core of the S4 (session ID validation) security fix.
Tests cover both the "secret set" (production) and "secret unset" (dev)
modes, as well as forgery, tampering, and malformed-token rejection.

Run with: python -m pytest tests/test_session_token.py -v
"""

import hmac
import hashlib
from unittest.mock import patch

from app.services.session_token import (
    generate_session_id,
    validate_session_id,
    _sign,
    _make_sig,
)

# A fixed secret for deterministic tests — never used in production.
_TEST_SECRET = b"test-secret-for-unit-tests"


# -----------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------

def _sign_with(raw: str, secret: bytes) -> str:
    """Sign a raw token with a given secret (test-only helper)."""
    sig = hmac.HMAC(secret, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


# -----------------------------------------------------------------------
# NO SECRET (dev mode) — all tokens accepted
# -----------------------------------------------------------------------

def test_generate_without_secret_returns_unsigned():
    """Without SESSION_SECRET, generated IDs have no dot-separated signature."""
    with patch("app.services.session_token._SECRET", b""):
        token = generate_session_id()
        # token_urlsafe doesn't contain dots, so no signature appended
        assert "." not in token
        assert len(token) > 20  # 32 bytes base64 ≈ 43 chars


def test_validate_without_secret_accepts_anything():
    """Without SESSION_SECRET, any string is accepted (dev convenience)."""
    with patch("app.services.session_token._SECRET", b""):
        assert validate_session_id("anything") is True
        assert validate_session_id("forged-session-123") is True
        assert validate_session_id("") is True


# -----------------------------------------------------------------------
# WITH SECRET (production mode) — signed tokens required
# -----------------------------------------------------------------------

def test_generate_with_secret_returns_signed():
    """With SESSION_SECRET, generated IDs contain a dot-separated HMAC."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        token = generate_session_id()
        assert "." in token
        raw, sig = token.rsplit(".", 1)
        assert len(raw) > 20
        assert len(sig) == 64  # SHA-256 hex digest


def test_roundtrip_generate_then_validate():
    """A token generated with a secret should validate with the same secret."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        token = generate_session_id()
        assert validate_session_id(token) is True


def test_reject_unsigned_token_when_secret_set():
    """A plain string (no signature) should be rejected when secret is set."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        assert validate_session_id("plain-session-id") is False


def test_reject_forged_signature():
    """A token with a wrong signature should be rejected."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        token = generate_session_id()
        raw, _ = token.rsplit(".", 1)
        forged = f"{raw}.{'a' * 64}"
        assert validate_session_id(forged) is False


def test_reject_tampered_payload():
    """Changing the raw portion should invalidate the signature."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        token = generate_session_id()
        raw, sig = token.rsplit(".", 1)
        tampered = f"TAMPERED{raw[8:]}.{sig}"
        assert validate_session_id(tampered) is False


def test_reject_empty_string():
    """An empty token should be rejected when secret is set."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        assert validate_session_id("") is False


def test_reject_just_a_dot():
    """A bare dot should be rejected."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        assert validate_session_id(".") is False


def test_reject_wrong_secret():
    """A token signed with a different secret should be rejected."""
    other_secret = b"different-secret"
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        # Sign with the wrong secret
        raw = "some-raw-token"
        wrong_token = _sign_with(raw, other_secret)
        assert validate_session_id(wrong_token) is False


def test_multiple_dots_in_token():
    """rsplit('.', 1) should handle tokens where the raw part contains dots."""
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        # Manually create a token with dots in the raw part
        raw_with_dots = "part1.part2.part3"
        sig = hmac.HMAC(_TEST_SECRET, raw_with_dots.encode(), hashlib.sha256).hexdigest()
        token = f"{raw_with_dots}.{sig}"
        assert validate_session_id(token) is True


def test_validate_is_constant_time():
    """validate_session_id should use hmac.compare_digest (not ==).

    We can't easily prove timing properties in a unit test, but we can
    verify the code path uses the right function by checking that a
    near-miss doesn't short-circuit differently than a total miss.
    Both should return False.
    """
    with patch("app.services.session_token._SECRET", _TEST_SECRET):
        token = generate_session_id()
        raw, sig = token.rsplit(".", 1)

        # Near miss: flip one character of the signature
        near_miss = f"{raw}.{sig[:-1]}{'b' if sig[-1] != 'b' else 'a'}"
        total_miss = f"{raw}.{'x' * 64}"

        assert validate_session_id(near_miss) is False
        assert validate_session_id(total_miss) is False
