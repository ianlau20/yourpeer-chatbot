from fastapi import APIRouter
from app.models.chat_models import ChatRequest
from app.services.chatbot import generate_reply

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/")
def chat(request: ChatRequest):
    response = generate_reply(request.message)
    return {"response": response}