import uuid

from app.llm.gemini_client import gemini_reply
from app.services.session_store import get_session_slots, save_session_slots
from app.services.slot_extractor import (
    extract_slots,
    is_enough_to_answer,
    merge_slots,
    next_follow_up_question,
)

def _build_help_prompt(user_message: str, slots: dict) -> str:
    return (
        "You are a helpful assistant for people seeking local support services.\n"
        "Be concise and practical.\n"
        f"Known context: {slots}\n"
        f"User message: {user_message}\n\n"
        "If enough detail exists, provide helpful next-step guidance now. "
        "Do not ask multiple follow-up questions."
    )

def generate_reply(message: str, session_id: str | None = None) -> dict:
    if not session_id:
        session_id = str(uuid.uuid4())

    existing = get_session_slots(session_id)
    extracted = extract_slots(message)
    merged = merge_slots(existing, extracted)
    save_session_slots(session_id, merged)

    # If enough detail exists, provide helpful next-step guidance now.
    if is_enough_to_answer(merged):
        prompt = _build_help_prompt(message, merged)
        bot_response = gemini_reply(prompt)
        return {
            "session_id": session_id,
            "response": bot_response,
            "follow_up_needed": False,
            "slots": merged,
        }

    # Otherwise, ask one targeted follow-up question.
    follow_up = next_follow_up_question(merged)
    return {
        "session_id": session_id,
        "response": follow_up,
        "follow_up_needed": True,
        "slots": merged,
    }
