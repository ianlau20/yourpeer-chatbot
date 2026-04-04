from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional
from app.models.chat_models import ChatRequest, ChatResponse
from app.services.chatbot import generate_reply
from app.services.audit_log import log_feedback

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    result = generate_reply(
        message=request.message,
        session_id=request.session_id,
    )
    return result


class FeedbackRequest(BaseModel):
    session_id: str
    rating: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(None, max_length=500)


@router.post("/feedback")
async def feedback(request: FeedbackRequest):
    """Record a thumbs up/down rating from the user."""
    log_feedback(
        session_id=request.session_id,
        rating=request.rating,
        comment=request.comment,
    )
    return {"ok": True}