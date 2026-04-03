from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routes.chat import router as chat_router
from app.routes.admin import router as admin_router

app = FastAPI(
    title="YourPeer Chatbot API",
    description="A chatbot for the YourPeer network by Streetlives.",
)

# --- CORS ---
# Allow all origins in demo mode so the frontend works from any URL.
# Tighten this for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API routes (registered FIRST so they take priority) ---
app.include_router(chat_router)
app.include_router(admin_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# --- Serve frontend static files ---
# In production (Render), the frontend folder sits one level up from backend/.
# Locally, it also sits at ../frontend/.
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# Known API path prefixes that should never be handled by the static file server.
_API_PREFIXES = {"chat", "api", "admin", "docs", "redoc", "openapi.json"}

if FRONTEND_DIR.exists():
    # Serve index.html at the root
    @app.get("/")
    def serve_frontend():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    # Serve individual frontend files (styles.css, app.js, etc.)
    # Only matches actual files — does NOT intercept API paths.
    @app.get("/{filename:path}")
    def serve_file(filename: str):
        # Don't intercept API routes
        first_segment = filename.split("/")[0] if filename else ""
        if first_segment in _API_PREFIXES:
            # Let FastAPI's normal routing handle it.
            # Returning 404 here allows the default handlers to kick in.
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )

        file_path = FRONTEND_DIR / filename
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        # Unknown path — serve index.html as fallback
        return FileResponse(str(FRONTEND_DIR / "index.html"))
else:
    @app.get("/")
    def root():
        return {"message": "YourPeer chatbot backend is running. Frontend not found."}
