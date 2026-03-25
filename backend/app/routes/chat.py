from fastapi import APIRouter
from app.models.chat_models import ChatRequest, ChatResponse
from app.services.chatbot import generate_reply

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    result = generate_reply(
        message=request.message,
        session_id=request.session_id,
    )
    return result