"""
Tests for main.py — FastAPI app configuration (headless API mode).

The backend is a headless API. All HTML is served by Next.js.

Covers:
    health     — GET /api/health
    root       — GET / → JSON message
    CORS       — headers present on responses + preflight

Run with: python -m pytest tests/test_main.py -v
Or just:  python tests/test_main.py
"""



from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# -----------------------------------------------------------------------
# HEALTH
# -----------------------------------------------------------------------

def test_health():
    """GET /api/health should return ok."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# -----------------------------------------------------------------------
# ROOT — JSON message (no static file serving)
# -----------------------------------------------------------------------

def test_root_returns_json():
    """GET / should return a JSON message indicating the API is running."""
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "message" in data
    assert "running" in data["message"].lower()


# -----------------------------------------------------------------------
# API routes are reachable
# -----------------------------------------------------------------------

def test_api_health_routed():
    """/api/health should be handled by the API router."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_chat_route_exists():
    """POST /chat/ should be handled by the chat router (not 404)."""
    # Will fail validation without a body, but should not be a 404
    r = client.post("/chat/", json={})
    assert r.status_code != 404


def test_admin_api_stats_routed():
    """GET /admin/api/stats should be handled by the admin router."""
    r = client.get("/admin/api/stats")
    assert r.status_code == 200


# -----------------------------------------------------------------------
# CORS HEADERS
# -----------------------------------------------------------------------

def test_cors_headers_present():
    """Responses should include CORS allow-origin header."""
    r = client.get("/api/health", headers={"Origin": "https://example.com"})
    assert r.status_code == 200
    origin = r.headers.get("access-control-allow-origin")
    assert origin in ("*", "https://example.com"), f"Expected CORS origin, got: {origin}"


def test_cors_preflight():
    """OPTIONS preflight should return CORS headers."""
    r = client.options(
        "/chat/",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    origin = r.headers.get("access-control-allow-origin")
    assert origin in ("*", "https://example.com"), f"Expected CORS origin, got: {origin}"
    assert "POST" in r.headers.get("access-control-allow-methods", "")


# -----------------------------------------------------------------------
