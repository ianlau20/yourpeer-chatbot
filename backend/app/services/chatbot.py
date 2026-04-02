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


def _format_results(results: dict) -> str:
    """
    Format query results as readable service cards.
    No LLM synthesis — just structured field mapping.
    """
    count = results["result_count"]
    if count == 0:
        return None

    lines = [f"I found {count} option(s) for you:\n"]

    for i, svc in enumerate(results["services"], 1):
        lines.append(f"{i}. {svc['service_name']}")
        if svc.get("organization"):
            lines.append(f"   {svc['organization']}")
        if svc.get("address"):
            lines.append(f"   {svc['address']}")
        if svc.get("phone"):
            lines.append(f"   Phone: {svc['phone']}")
        if svc.get("fees"):
            lines.append(f"   Cost: {svc['fees']}")
        if svc.get("description"):
            # Truncate long descriptions
            desc = svc["description"]
            if len(desc) > 120:
                desc = desc[:117] + "..."
            lines.append(f"   {desc}")
        lines.append("")

    if results.get("relaxed"):
        lines.append("(I broadened the search a bit to find these results.)")

    return "\n".join(lines)


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


def generate_reply(message: str, session_id: str | None = None) -> dict:
    if not session_id:
        session_id = str(uuid.uuid4())

    existing = get_session_slots(session_id)
    extracted = extract_slots(message)
    merged = merge_slots(existing, extracted)
    save_session_slots(session_id, merged)

    # If enough detail exists, query the database for real services.
    if is_enough_to_answer(merged):

        try:
            results = query_services(
                service_type=merged.get("service_type"),
                location=merged.get("location"),
                age=merged.get("age"),
            )

            if results.get("error"):
                # Template not found or other query-level error —
                # fall back to LLM for a helpful response.
                logger.warning(f"Query error: {results['error']}")
                prompt = _build_help_prompt(message, merged)
                bot_response = gemini_reply(prompt)
            elif results["result_count"] > 0:
                bot_response = _format_results(results)
            else:
                bot_response = _no_results_message(merged)

        except Exception as e:
            # DB connection failure or other unexpected error —
            # fall back to LLM so the user still gets a response.
            logger.error(f"Database query failed: {e}")
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