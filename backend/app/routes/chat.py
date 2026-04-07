from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
import uuid

from app.models.chat_models import ChatRequest, ChatResponse
from app.services.chatbot import generate_reply
from app.services.audit_log import log_feedback
from app.services.session_token import generate_session_id, validate_session_id

router = APIRouter(prefix="/chat", tags=["chat"])


class FeedbackRequest(BaseModel):
    session_id: str
    rating: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(None, max_length=500)


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, raw: Request):
    request_id = raw.headers.get("x-request-id") or str(uuid.uuid4())
    session_id = request.session_id

    if session_id:
        if not validate_session_id(session_id):
            raise HTTPException(status_code=403, detail="Invalid session token")
    else:
        session_id = generate_session_id()

    result = generate_reply(
        message=request.message,
        session_id=session_id,
        latitude=request.latitude,
        longitude=request.longitude,
        request_id=request_id,
    )
    # Make sure the (possibly new) session_id is returned to the client
    result["session_id"] = session_id
    return JSONResponse(
        content=ChatResponse(**result).model_dump(),
        headers={"X-Request-ID": request_id},
    )


@router.post("/feedback")
async def feedback(request: FeedbackRequest):
    if not validate_session_id(request.session_id):
        raise HTTPException(status_code=403, detail="Invalid session token")
    log_feedback(
        session_id=request.session_id,
        rating=request.rating,
        comment=request.comment,
    )
    return {"ok": True}
