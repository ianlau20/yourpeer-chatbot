import uuid
import logging

from app.llm.gemini_client import gemini_reply
from app.services.session_store import get_session_slots, save_session_slots
from app.services.slot_extractor import (
    extract_slots,
    is_enough_to_answer,
    merge_slots,
    next_follow_up_question,
)
from app.rag import query_services

logger = logging.getLogger(__name__)


def _no_results_message(slots: dict) -> str:
    """Helpful message when no services match the query."""
    service = slots.get("service_type", "services")
    location = slots.get("location", "your area")
    return (
        f"I wasn't able to find {service} services in {location} "
        f"matching your criteria. You could try a nearby area, or "
        f"I can connect you with a peer navigator who may know of "
        f"other options. Would you like to try a different location?"
    )


def _build_help_prompt(user_message: str, slots: dict) -> str:
    """Fallback prompt for when DB query is unavailable."""
    return (
        "You are a helpful assistant for people seeking local support services.\n"
        "Be concise and practical.\n"
        f"Known context: {slots}\n"
        f"User message: {user_message}\n\n"
        "If enough detail exists, provide helpful next-step guidance now. "
        "Do not ask multiple follow-up questions."
    )


def _fallback_response(message: str, slots: dict) -> str:
    """Try Gemini, and if that also fails, return a safe static message."""
    try:
        prompt = _build_help_prompt(message, slots)
        return gemini_reply(prompt)
    except Exception as e:
        logger.error(f"Gemini fallback also failed: {e}")
        return (
            "I'm having trouble looking that up right now. "
            "Please try again in a moment, or visit yourpeer.nyc "
            "to search for services directly."
        )


def generate_reply(message: str, session_id: str | None = None) -> dict:
    if not session_id:
        session_id = str(uuid.uuid4())

    existing = get_session_slots(session_id)
    extracted = extract_slots(message)
    merged = merge_slots(existing, extracted)
    save_session_slots(session_id, merged)

    # If enough detail exists, query the database for real services.
    if is_enough_to_answer(merged):

        # Always initialize so we never hit UnboundLocalError
        bot_response = None
        services_list = []
        result_count = 0
        relaxed = False

        try:
            results = query_services(
                service_type=merged.get("service_type"),
                location=merged.get("location"),
                age=merged.get("age"),
            )

            if results.get("error"):
                logger.warning(f"Query error: {results['error']}")
                bot_response = _fallback_response(message, merged)

            elif results["result_count"] > 0:
                services_list = results["services"]
                result_count = results["result_count"]
                relaxed = results.get("relaxed", False)

                qualifier = ""
                if relaxed:
                    qualifier = " (I broadened the search a bit)"

                bot_response = (
                    f"I found {result_count} option(s) for you{qualifier}. "
                    f"Here's what's available:"
                )
            else:
                bot_response = _no_results_message(merged)

        except Exception as e:
            logger.error(f"Database query failed: {e}")
            bot_response = _fallback_response(message, merged)

        # Final safety net — should never trigger, but guarantees no crash
        if bot_response is None:
            bot_response = _fallback_response(message, merged)

        return {
            "session_id": session_id,
            "response": bot_response,
            "follow_up_needed": False,
            "slots": merged,
            "services": services_list,
            "result_count": result_count,
            "relaxed_search": relaxed,
        }

    # Otherwise, ask one targeted follow-up question.
    follow_up = next_follow_up_question(merged)
    return {
        "session_id": session_id,
        "response": follow_up,
        "follow_up_needed": True,
        "slots": merged,
        "services": [],
        "result_count": 0,
        "relaxed_search": False,
    }
