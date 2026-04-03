from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
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
        first_segment = filename.split("/")[0] if filename else ""

        # Don't intercept API routes
        if first_segment in _API_PREFIXES:
            # Redirect bare /admin to /admin/ so the router picks it up
            if filename == "admin":
                from fastapi.responses import RedirectResponse
                return RedirectResponse(url="/admin/", status_code=301)
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"},
            )

        # Serve static files (styles.css, app.js, etc.)
        file_path = FRONTEND_DIR / filename
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))

        # Unknown path — serve 404 page
        not_found_page = FRONTEND_DIR / "404.html"
        if not_found_page.exists():
            return FileResponse(str(not_found_page), status_code=404)
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    # --- Global exception handler — serve 500 page for unhandled errors ---
    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc: Exception):
        # For API requests, return JSON
        if request.url.path.startswith(("/chat", "/api", "/admin/api")):
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
        # For browser requests, serve the 500 page
        error_page = FRONTEND_DIR / "500.html"
        if error_page.exists():
            return FileResponse(str(error_page), status_code=500)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
else:
    @app.get("/")
    def root():
        return {"message": "YourPeer chatbot backend is running. Frontend not found."}
