from typing import Optional, List
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ServiceCard(BaseModel):
    """Structured service result for frontend rendering."""
    service_name: str
    organization: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    fees: Optional[str] = None
    additional_info: Optional[str] = None
    yourpeer_url: Optional[str] = None
    hours_today: Optional[str] = None
    is_open: Optional[str] = None


class QuickReply(BaseModel):
    """A tappable button option shown below a bot message."""
    label: str
    value: str  # the text sent as a user message when tapped


class ChatResponse(BaseModel):
    session_id: str
    response: str
    follow_up_needed: bool
    slots: dict
    services: List[ServiceCard] = []
    result_count: int = 0
    relaxed_search: bool = False
    quick_replies: List[QuickReply] = []
