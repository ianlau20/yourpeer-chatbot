import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat import router as chat_router
from app.routes.admin import router as admin_router
from app.dependencies import RateLimitMiddleware, CSRFMiddleware
app = FastAPI(
    title="YourPeer Chatbot API",
    description="A chatbot for the YourPeer network by Streetlives.",
)
# --- CORS ---
# Allowed origins are read from the CORS_ALLOWED_ORIGINS env var
# (comma-separated).  Defaults to localhost for local dev.
# In production, set to the actual frontend domain(s).
_DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CSRF protection ---
# Validates Origin header on POST/PUT/DELETE to prevent cross-site forgery.
app.add_middleware(CSRFMiddleware)
# --- Rate limiting ---
# Protects /chat/ and /chat/feedback. Admin and health routes are exempt.
app.add_middleware(RateLimitMiddleware)
# --- API routes ---
app.include_router(chat_router)
app.include_router(admin_router)
@app.get("/api/health")
def health():
    return {"status": "ok"}
@app.get("/")
def root():
    return {"message": "YourPeer chatbot API is running. Frontend served by Next.js."}