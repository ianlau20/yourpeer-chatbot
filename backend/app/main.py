from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.chat import router as chat_router

app = FastAPI(title="YourPeer Chatbot API", description="A chatbot for the YourPeer network by Streetlives.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://[::1]:5500",
        "http://[::]:5500",
        "[::]:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)

@app.get("/")
def root():
    return {"message": "YourPeer chatbot backend is running."}