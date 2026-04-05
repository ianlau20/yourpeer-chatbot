"""
FastAPI dependencies for request-level concerns (rate limiting, auth, etc.).
"""
import json
import logging
import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from app.services.rate_limiter import (
    check_rate_limit,
    CHAT_SESSION_LIMITS,
    CHAT_IP_LIMITS,
    FEEDBACK_SESSION_LIMITS,
)
# ---------------------------------------------------------------------------
# Admin API key authentication
# ---------------------------------------------------------------------------
def require_admin_key(request: Request) -> None:
    """Dependency that enforces admin API key authentication.
    When ADMIN_API_KEY is set, requests must include a matching
    ``Authorization: Bearer <key>`` header.  When the env var is
    unset, all requests are allowed (local-dev convenience).
    """
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected:
        return  # No key configured — open access (dev mode)
    auth = request.headers.get("authorization", "")
    if auth == f"Bearer {expected}":
        return
    raise HTTPException(
        status_code=401,
        detail="Missing or invalid admin API key",
    )
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# 429 response body — compassionate, with crisis resources
# ---------------------------------------------------------------------------
_RATE_LIMIT_RESPONSE = (
    "You\u2019re sending messages very quickly. "
    "Please wait a moment and try again."
)
_CRISIS_RESOURCES = (
    "If you need immediate help, call 311 for NYC services "
    "or 988 for the Suicide & Crisis Lifeline."
)
# ---------------------------------------------------------------------------
# Client IP extraction
# ---------------------------------------------------------------------------
def get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting proxy headers.
    Render (and most reverse proxies) set ``X-Forwarded-For``.
    We take the *first* entry — the original client — and fall back to
    the direct connection address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # "client, proxy1, proxy2" → take the client
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
# ---------------------------------------------------------------------------
# Rate-limit middleware
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limits to chat endpoints as middleware.
    Using middleware instead of Depends() because the rate limiter needs the
    raw request body (for session_id) before the route handler parses it.
    FastAPI's body caching makes this safe — the route handler still receives
    the full body.
    Only applies to POST /chat/ and POST /chat/feedback.
    """
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ):
        if request.method != "POST":
            return await call_next(request)
        path = request.url.path.rstrip("/")
        if path == "/chat":
            return await self._check_chat(request, call_next)
        elif path == "/chat/feedback":
            return await self._check_feedback(request, call_next)
        return await call_next(request)
    async def _check_chat(self, request: Request, call_next):
        client_ip = get_client_ip(request)
        session_id = await _extract_session_id(request)
        # Check per-session limits (if session_id is present)
        if session_id:
            result = check_rate_limit(f"session:{session_id}", CHAT_SESSION_LIMITS)
            if not result.allowed:
                logger.warning(
                    "Rate limited session=%s ip=%s (session limit: %d/%ds)",
                    session_id, client_ip, result.limit, result.window,
                )
                return _build_429(result.retry_after)
        # Check per-IP limits (always)
        result = check_rate_limit(f"ip:{client_ip}", CHAT_IP_LIMITS)
        if not result.allowed:
            logger.warning(
                "Rate limited ip=%s (IP limit: %d/%ds)",
                client_ip, result.limit, result.window,
            )
            return _build_429(result.retry_after)
        return await call_next(request)
    async def _check_feedback(self, request: Request, call_next):
        session_id = await _extract_session_id(request)
        if session_id:
            result = check_rate_limit(
                f"feedback:{session_id}", FEEDBACK_SESSION_LIMITS,
            )
            if not result.allowed:
                return _build_429(result.retry_after)
        return await call_next(request)
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _extract_session_id(request: Request) -> str | None:
    """Read session_id from the JSON body without consuming it."""
    try:
        body = await request.body()
        if body:
            data = json.loads(body)
            return data.get("session_id")
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None
def _build_429(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": _RATE_LIMIT_RESPONSE,
            "crisis_resources": _CRISIS_RESOURCES,
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
# ---------------------------------------------------------------------------
# CORS / CSRF — shared origin list
# ---------------------------------------------------------------------------

_DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"


def get_allowed_origins() -> list[str]:
    """Return the list of allowed CORS origins.

    Used by both CORSMiddleware (in main.py) and CSRFMiddleware (below).
    Single source of truth — avoids the two lists drifting apart.
    """
    return [
        o.strip()
        for o in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
        if o.strip()
    ]
class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state-changing requests from browsers.
    Checks the ``Origin`` header (or ``Referer``) on POST/PUT/DELETE
    requests against the allowed CORS origins.  Non-browser clients
    (curl, Postman) that send no ``Origin``/``Referer``/``Sec-Fetch-Site``
    headers are allowed through.
    """
    _SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if request.method in self._SAFE_METHODS:
            return await call_next(request)
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        sec_fetch = request.headers.get("sec-fetch-site")
        # Non-browser clients (no Origin, no Referer, no Sec-Fetch-Site) → allow
        if not origin and not referer and not sec_fetch:
            return await call_next(request)
        allowed = get_allowed_origins()
        # Check Origin header
        if origin:
            if origin in allowed:
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request rejected"},
            )
        # Fallback: check Referer (extract origin portion)
        if referer:
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            ref_origin = f"{parsed.scheme}://{parsed.netloc}"
            if ref_origin in allowed:
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request rejected"},
            )
        # Browser sent Sec-Fetch-Site but no Origin/Referer — reject
        return JSONResponse(
            status_code=403,
            content={"detail": "Cross-origin request rejected"},
        )
