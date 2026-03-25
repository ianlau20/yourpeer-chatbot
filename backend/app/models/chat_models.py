from typing import Optional
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    session_id: str
    response: str
    follow_up_needed: bool
    slots: dict