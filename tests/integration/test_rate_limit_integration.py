"""
Integration tests for rate limiting on chat routes.

Verifies that the RateLimitMiddleware correctly returns 429 responses
with compassionate messaging and Retry-After headers.

Run: pytest tests/test_rate_limit_integration.py -v
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import app
from app.services.rate_limiter import clear
from conftest import MOCK_EMPTY_RESULTS

client = TestClient(app)


def _post_chat(message="hello", session_id="test-session", headers=None):
    return client.post(
        "/chat/",
        json={"message": message, "session_id": session_id},
        headers=headers,
    )


# -----------------------------------------------------------------------
# 429 RESPONSE — PER-SESSION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_SESSION_LIMITS", [(60, 3), (3600, 60), (86400, 200)])
def test_chat_returns_429_when_session_rate_limited(mock_claude, mock_query):
    """Exceeding per-session per-minute limit should return 429."""
    clear()
    sid = "rate-limit-session"

    for _ in range(3):
        r = _post_chat(session_id=sid)
        assert r.status_code == 200

    r = _post_chat(session_id=sid)
    assert r.status_code == 429


@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_SESSION_LIMITS", [(60, 1)])
def test_429_response_body(mock_claude, mock_query):
    """429 response should include compassionate message and crisis resources."""
    clear()
    _post_chat(session_id="body-test")
    r = _post_chat(session_id="body-test")

    assert r.status_code == 429
    data = r.json()
    assert "wait" in data["detail"].lower()
    assert "crisis_resources" in data
    assert "988" in data["crisis_resources"]
    assert "311" in data["crisis_resources"]
    assert "retry_after" in data
    assert isinstance(data["retry_after"], int)
    assert data["retry_after"] >= 1


@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_SESSION_LIMITS", [(60, 1)])
def test_429_includes_retry_after_header(mock_claude, mock_query):
    """429 response should include Retry-After header."""
    clear()
    _post_chat(session_id="header-test")
    r = _post_chat(session_id="header-test")

    assert r.status_code == 429
    assert "retry-after" in r.headers
    assert int(r.headers["retry-after"]) >= 1


# -----------------------------------------------------------------------
# 429 RESPONSE — PER-IP
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_IP_LIMITS", [(60, 3)])
def test_ip_limit_aggregates_sessions(mock_claude, mock_query):
    """Multiple sessions from one IP should aggregate toward IP limit."""
    clear()
    _post_chat(session_id="ip-s1")
    _post_chat(session_id="ip-s2")
    _post_chat(session_id="ip-s3")

    r = _post_chat(session_id="ip-s4")
    assert r.status_code == 429


# -----------------------------------------------------------------------
# SESSION ISOLATION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_SESSION_LIMITS", [(60, 2)])
def test_different_sessions_independent(mock_claude, mock_query):
    """Different session IDs should have independent rate limits."""
    clear()
    _post_chat(session_id="iso-a")
    _post_chat(session_id="iso-a")
    r = _post_chat(session_id="iso-a")
    assert r.status_code == 429

    # Session B should still work
    r = _post_chat(session_id="iso-b")
    assert r.status_code == 200


# -----------------------------------------------------------------------
# NON-RATE-LIMITED ROUTES
# -----------------------------------------------------------------------

def test_health_endpoint_not_rate_limited():
    """GET /api/health should never be rate limited."""
    clear()
    for _ in range(20):
        r = client.get("/api/health")
        assert r.status_code == 200


def test_admin_routes_not_rate_limited():
    """Admin API routes should not be rate limited."""
    clear()
    for _ in range(20):
        r = client.get("/admin/api/stats")
        assert r.status_code == 200


# -----------------------------------------------------------------------
# MISSING SESSION_ID
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_IP_LIMITS", [(60, 2)])
def test_no_session_id_uses_ip_only(mock_claude, mock_query):
    """Requests without session_id should still be rate limited by IP."""
    clear()
    client.post("/chat/", json={"message": "hi"})
    client.post("/chat/", json={"message": "hi"})
    r = client.post("/chat/", json={"message": "hi"})
    assert r.status_code == 429


# -----------------------------------------------------------------------
# FEEDBACK ENDPOINT
# -----------------------------------------------------------------------

@patch("app.dependencies.FEEDBACK_SESSION_LIMITS", [(60, 2)])
def test_feedback_has_separate_limit():
    """Feedback endpoint should have its own rate limit."""
    clear()
    sid = "feedback-test"
    for _ in range(2):
        r = client.post("/chat/feedback", json={
            "session_id": sid, "rating": "up",
        })
        assert r.status_code == 200

    r = client.post("/chat/feedback", json={
        "session_id": sid, "rating": "up",
    })
    assert r.status_code == 429


# -----------------------------------------------------------------------
# X-Forwarded-For HANDLING
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="test")
@patch("app.dependencies.CHAT_IP_LIMITS", [(60, 2)])
def test_x_forwarded_for_used_for_ip(mock_claude, mock_query):
    """Rate limiter should use X-Forwarded-For for IP identification."""
    clear()

    for _ in range(2):
        _post_chat(
            session_id="xff-a",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )

    # Different IP should still have quota
    r = _post_chat(
        session_id="xff-b",
        headers={"X-Forwarded-For": "5.6.7.8"},
    )
    assert r.status_code == 200

    # Original IP should be blocked
    r = _post_chat(
        session_id="xff-c",
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert r.status_code == 429
