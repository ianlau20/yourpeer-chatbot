import uuid
import re
import logging

from app.llm.gemini_client import gemini_reply
from app.services.session_store import (
    get_session_slots,
    save_session_slots,
    clear_session,
)
from app.services.slot_extractor import (
    extract_slots,
    is_enough_to_answer,
    merge_slots,
    next_follow_up_question,
)
from app.rag import query_services

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MESSAGE CLASSIFICATION
# ---------------------------------------------------------------------------
# Lightweight keyword router that decides how to handle a message BEFORE
# touching the slot extractor. This keeps the conversation feeling natural
# without sending every "thanks" or "hi" through a DB query.

_RESET_PHRASES = [
    "start over", "reset", "clear", "new search", "begin again",
    "restart", "start again", "nevermind", "never mind", "cancel",
]

_GREETING_PHRASES = [
    "hi", "hey", "hello", "sup", "yo", "good morning", "good afternoon",
    "good evening", "whats up", "what's up",
]

_THANKS_PHRASES = [
    "thanks", "thank you", "thx", "ty", "appreciate it",
    "that helps", "perfect", "great thanks", "awesome",
]

_HELP_PHRASES = [
    "help", "what can you do", "how does this work",
    "what is this", "who are you", "what do you do",
    "how do i use this", "instructions",
]


def _classify_message(text: str) -> str:
    """
    Classify a message into a routing category.

    Returns one of:
        "reset"       — user wants to start over
        "greeting"    — hi / hello / hey
        "thanks"      — thank you / thx
        "help"        — what can you do / how does this work
        "service"     — contains a service-related intent or slot data
        "general"     — everything else (conversational, follow-up, unclear)
    """
    lower = text.lower().strip()

    # Strip punctuation for matching
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # Check reset first — highest priority
    for phrase in _RESET_PHRASES:
        if phrase in cleaned:
            return "reset"

    # Check greetings (only if the message is short — "hi where's food"
    # should be classified as a service request, not a greeting)
    if len(cleaned.split()) <= 3:
        for phrase in _GREETING_PHRASES:
            if cleaned == phrase or cleaned.startswith(phrase + " "):
                return "greeting"

    # Check thanks
    for phrase in _THANKS_PHRASES:
        if phrase in cleaned:
            return "thanks"

    # Check help
    for phrase in _HELP_PHRASES:
        if phrase in cleaned:
            return "help"

    # Try slot extraction — if it finds anything, it's a service message
    extracted = extract_slots(text)
    has_new_slot = any(
        v is not None for v in extracted.values()
    )
    if has_new_slot:
        return "service"

    # Nothing matched — general conversation
    return "general"


# ---------------------------------------------------------------------------
# RESPONSE BUILDERS
# ---------------------------------------------------------------------------

_GREETING_RESPONSE = (
    "Hey! I'm here to help you find services in NYC — things like "
    "food, shelter, showers, clothing, health care, and more. "
    "What are you looking for today?"
)

_RESET_RESPONSE = (
    "No problem, let's start fresh. "
    "What kind of help are you looking for?"
)

_THANKS_RESPONSE = (
    "You're welcome! Let me know if you need anything else — "
    "I can search for food, shelter, clothing, health care, "
    "legal help, jobs, and more."
)

_HELP_RESPONSE = (
    "I can help you find free services in New York City. "
    "Just tell me what you need and where you are — for example, "
    '"I need food in Brooklyn" or "shelter in Queens." '
    "I'll search real, verified listings from YourPeer and "
    "show you what's available with addresses and hours.\n\n"
    "You can also say 'start over' anytime to begin a new search."
)


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


def _build_conversational_prompt(user_message: str, slots: dict) -> str:
    """Prompt for general conversational messages that aren't service queries."""
    slot_context = ""
    if slots:
        filled = {k: v for k, v in slots.items() if v is not None}
        if filled:
            slot_context = f"\nContext from our conversation so far: {filled}\n"

    return (
        "You are YourPeer, a friendly assistant that helps people find "
        "free social services in New York City (food, shelter, clothing, "
        "showers, health care, mental health, legal help, employment, etc.).\n"
        "You are warm, respectful, and concise.\n"
        "You do NOT make up service names, addresses, or phone numbers.\n"
        "If the user seems to be asking about a service, gently steer them "
        "to tell you what they need and where they are so you can search.\n"
        "Keep your response to 1-3 sentences.\n"
        f"{slot_context}"
        f"User message: {user_message}"
    )


def _fallback_response(message: str, slots: dict) -> str:
    """Try Gemini for conversational response, with a safe static fallback."""
    try:
        prompt = _build_conversational_prompt(message, slots)
        return gemini_reply(prompt)
    except Exception as e:
        logger.error(f"Gemini fallback also failed: {e}")
        return (
            "I'm having trouble right now. "
            "You can try again in a moment, or visit yourpeer.nyc "
            "to search for services directly."
        )


# ---------------------------------------------------------------------------
# EMPTY RESPONSE HELPER
# ---------------------------------------------------------------------------

def _empty_reply(session_id: str, response: str, slots: dict) -> dict:
    """Build a reply dict with no service results."""
    return {
        "session_id": session_id,
        "response": response,
        "follow_up_needed": False,
        "slots": slots,
        "services": [],
        "result_count": 0,
        "relaxed_search": False,
    }


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def generate_reply(message: str, session_id: str | None = None) -> dict:
    if not session_id:
        session_id = str(uuid.uuid4())

    existing = get_session_slots(session_id)
    category = _classify_message(message)

    # --- Reset ---
    if category == "reset":
        clear_session(session_id)
        return _empty_reply(session_id, _RESET_RESPONSE, {})

    # --- Greeting ---
    if category == "greeting":
        # If they have existing slots, acknowledge and re-offer
        if existing and any(v is not None for v in existing.values()):
            response = (
                "Hey again! I still have your earlier search info. "
                "Want to keep going, or would you like to start over?"
            )
            return _empty_reply(session_id, response, existing)
        return _empty_reply(session_id, _GREETING_RESPONSE, existing)

    # --- Thanks ---
    if category == "thanks":
        return _empty_reply(session_id, _THANKS_RESPONSE, existing)

    # --- Help ---
    if category == "help":
        return _empty_reply(session_id, _HELP_RESPONSE, existing)

    # --- Service request or general conversation ---
    # Run slot extraction and merge with existing session
    extracted = extract_slots(message)
    merged = merge_slots(existing, extracted)
    save_session_slots(session_id, merged)

    # If enough detail exists, query the database
    if is_enough_to_answer(merged):

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

    # Not enough slots yet — but is this a service request or just conversation?
    if category == "service":
        # They mentioned something service-related but we need more info
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

    # --- General conversation ---
    # The message didn't match any service keywords and isn't a greeting/reset.
    # Use Gemini for a natural conversational response that gently steers
    # the user back toward telling us what they need.
    response = _fallback_response(message, merged)
    return _empty_reply(session_id, response, merged)
