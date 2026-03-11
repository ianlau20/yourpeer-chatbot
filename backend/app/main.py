from fastapi import FastAPI
from app.routes.chat import router as chat_router

app = FastAPI(title="YourPeer Chatbot API", description="A chatbot for the YourPeer network by Streetlives.")

app.include_router(chat_router)

@app.get("/")
def root():
    return {"message": "YourPeer chatbot backend is running."}