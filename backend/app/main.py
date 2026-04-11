from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat import router as chat_router
from app.routes.admin import router as admin_router
from app.dependencies import (
    RateLimitMiddleware, CSRFMiddleware, BodySizeLimitMiddleware,
    BotDetectionMiddleware, get_allowed_origins,
)
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup/shutdown lifecycle. Hydrates persisted data on boot."""
    from app.services import persistence
    if persistence.is_enabled():
        from app.services.audit_log import hydrate_from_db as hydrate_audit
        from app.services.session_store import hydrate_from_db as hydrate_sessions
        events = hydrate_audit()
        sessions = hydrate_sessions()
        logger.info(f"Startup hydration: {events} events, {sessions} sessions from SQLite")
    yield
    # Shutdown: close SQLite connection
    from app.services import persistence as p
    p.close()


app = FastAPI(
    title="YourPeer Chatbot API",
    description="A chatbot for the YourPeer network by Streetlives.",
    lifespan=lifespan,
)

# --- CORS ---
# Allowed origins are read from the CORS_ALLOWED_ORIGINS env var
# (comma-separated). Defaults to localhost for local dev.
# In production, set to the actual frontend domain(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CSRF protection ---
# Validates Origin header on POST/PUT/DELETE to prevent cross-site forgery.
app.add_middleware(CSRFMiddleware)

# --- Rate limiting ---
# Protects /chat/ and /chat/feedback. Admin and health routes are exempt.
app.add_middleware(RateLimitMiddleware)

# --- Body size limit ---
# Rejects oversized request bodies before parsing (50KB cap).
app.add_middleware(BodySizeLimitMiddleware)

# --- Bot detection ---
# Blocks known scanner User-Agents and bans IPs that probe honeypot paths.
app.add_middleware(BotDetectionMiddleware)

# --- API routes ---
app.include_router(chat_router)
app.include_router(admin_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "YourPeer chatbot API is running. Frontend served by Next.js."}
