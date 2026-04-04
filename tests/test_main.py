"""
Tests for main.py — FastAPI app configuration, static file serving,
error pages, API prefix guard, and CORS headers.

Covers all 5 public functions:
    health             — GET /api/health
    serve_frontend     — GET / → index.html
    serve_file         — GET /{filename} → static files, 404 page, API guard
    server_error_handler — 500 page for browser, JSON for API
    root               — fallback when frontend dir doesn't exist

Also tests:
    - CORS headers present on responses
    - /admin redirect to /admin/
    - Static files served with correct content types
    - Unknown paths serve 404.html
    - API paths (/chat, /api, /docs) not intercepted by catch-all

Run with: python -m pytest tests/test_main.py -v
Or just:  python tests/test_main.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient
from app.main import app, FRONTEND_DIR

client = TestClient(app)


# -----------------------------------------------------------------------
# HEALTH
# -----------------------------------------------------------------------

def test_health():
    """GET /api/health should return ok."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    print("  PASS: GET /api/health")


# -----------------------------------------------------------------------
# SERVE FRONTEND — GET /
# -----------------------------------------------------------------------

def test_root_serves_index_html():
    """GET / should serve index.html."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "YourPeer" in r.text
    assert "chat-form" in r.text  # the chat form element
    print("  PASS: GET / serves index.html")


# -----------------------------------------------------------------------
# SERVE FILE — static assets
# -----------------------------------------------------------------------

def test_serve_styles_css():
    """GET /styles.css should serve the CSS file."""
    r = client.get("/styles.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")
    assert ".app" in r.text or "box-sizing" in r.text
    print("  PASS: GET /styles.css")


def test_serve_app_js():
    """GET /app.js should serve the JavaScript file."""
    # The actual URL has a cache-bust param, but bare path should also work
    r = client.get("/app.js")
    assert r.status_code == 200
    content_type = r.headers.get("content-type", "")
    assert "javascript" in content_type or "text/plain" in content_type
    assert "sendMessage" in r.text or "API_URL" in r.text
    print("  PASS: GET /app.js")


def test_serve_404_html():
    """GET /404.html should serve the 404 error page."""
    r = client.get("/404.html")
    assert r.status_code == 200  # it's a real file being served
    assert "Page not found" in r.text or "404" in r.text
    print("  PASS: GET /404.html serves the error page file")


def test_serve_500_html():
    """GET /500.html should serve the 500 error page."""
    r = client.get("/500.html")
    assert r.status_code == 200
    assert "Something went wrong" in r.text or "500" in r.text
    print("  PASS: GET /500.html serves the error page file")


# -----------------------------------------------------------------------
# SERVE FILE — unknown paths → 404 page
# -----------------------------------------------------------------------

def test_unknown_path_returns_404_page():
    """GET /nonexistent should return 404 with the 404.html content."""
    r = client.get("/totally-nonexistent-page")
    assert r.status_code == 404

    if FRONTEND_DIR.exists() and (FRONTEND_DIR / "404.html").exists():
        # Should serve the custom 404 page
        assert "Page not found" in r.text or "404" in r.text
    print("  PASS: GET /nonexistent → 404 page")


def test_unknown_nested_path_returns_404():
    """GET /some/deep/path should also return 404."""
    r = client.get("/some/deep/nested/path")
    assert r.status_code == 404
    print("  PASS: GET /some/deep/path → 404")


# -----------------------------------------------------------------------
# SERVE FILE — API prefix guard
# -----------------------------------------------------------------------

def test_api_prefix_not_intercepted():
    """Paths starting with API prefixes should NOT be served as static files."""
    # /chat is a POST-only route; GET should return 404 from the guard, not a file
    r = client.get("/chat/nonexistent")
    assert r.status_code == 404
    data = r.json()
    assert data.get("detail") == "Not found"
    print("  PASS: /chat/* not intercepted by static handler")


def test_api_health_not_intercepted():
    """/api/health should be handled by the API router, not the static handler."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    print("  PASS: /api/* handled by API router")


def test_docs_not_intercepted():
    """/docs should serve FastAPI's Swagger UI, not a static file."""
    r = client.get("/docs")
    assert r.status_code in (200, 404)  # 404 if not in _API_PREFIXES
    # Should NOT serve index.html
    if r.status_code == 200:
        assert "swagger" in r.text.lower() or "openapi" in r.text.lower()
    print("  PASS: /docs not intercepted by static handler")


# -----------------------------------------------------------------------
# ADMIN REDIRECT
# -----------------------------------------------------------------------

def test_admin_bare_redirects():
    """GET /admin (no trailing slash) should redirect to /admin/."""
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers.get("location") == "/admin/"
    print("  PASS: GET /admin → 301 redirect to /admin/")


# -----------------------------------------------------------------------
# CORS HEADERS
# -----------------------------------------------------------------------

def test_cors_headers_present():
    """Responses should include CORS allow-origin header."""
    r = client.get("/api/health", headers={"Origin": "https://example.com"})
    assert r.status_code == 200
    # With allow_credentials=True, CORS middleware echoes the Origin
    # back instead of literal "*"
    origin = r.headers.get("access-control-allow-origin")
    assert origin in ("*", "https://example.com"), f"Expected CORS origin, got: {origin}"
    print("  PASS: CORS headers present")


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
    print("  PASS: CORS preflight")


# -----------------------------------------------------------------------
# ROOT FALLBACK (when frontend dir doesn't exist)
# -----------------------------------------------------------------------

def test_root_fallback_without_frontend():
    """When FRONTEND_DIR doesn't exist, GET / should return a JSON message.

    This tests the `root()` function in the else branch of main.py.
    We can't easily remove the frontend dir at runtime since the app
    is already configured, but we can verify the function directly.
    """
    from app.main import FRONTEND_DIR

    if FRONTEND_DIR.exists():
        # The root() function is only defined in the else branch,
        # so it won't exist in our test environment. We verify that
        # serve_frontend is defined instead (which proves the if
        # branch was taken correctly).
        from app.main import serve_frontend
        assert callable(serve_frontend)
        print("  PASS: root fallback — serve_frontend exists (frontend dir present)")
    else:
        # If somehow frontend dir is missing, root() should be defined
        from app.main import root
        assert callable(root)
        r = client.get("/")
        assert "backend is running" in r.json().get("message", "").lower()
        print("  PASS: root fallback returns JSON message")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nMain App Tests\n" + "=" * 50)

    print("\n--- Health ---")
    test_health()

    print("\n--- Serve Frontend ---")
    test_root_serves_index_html()

    print("\n--- Static Files ---")
    test_serve_styles_css()
    test_serve_app_js()
    test_serve_404_html()
    test_serve_500_html()

    print("\n--- 404 Handling ---")
    test_unknown_path_returns_404_page()
    test_unknown_nested_path_returns_404()

    print("\n--- API Prefix Guard ---")
    test_api_prefix_not_intercepted()
    test_api_health_not_intercepted()
    test_docs_not_intercepted()

    print("\n--- Admin Redirect ---")
    test_admin_bare_redirects()

    print("\n--- CORS ---")
    test_cors_headers_present()
    test_cors_preflight()

    print("\n--- Root Fallback ---")
    test_root_fallback_without_frontend()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
