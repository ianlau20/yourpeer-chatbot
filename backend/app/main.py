from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat import router as chat_router
from app.routes.admin import router as admin_router
from app.dependencies import RateLimitMiddleware

app = FastAPI(
    title="YourPeer Chatbot API",
    description="A chatbot for the YourPeer network by Streetlives.",
)

# --- CORS ---
# Next.js on :3000 calls FastAPI on :8000 during local dev.
# In production, tighten to the actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
