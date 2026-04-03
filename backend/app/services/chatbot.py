import uuid
import re
import os
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
from app.privacy.pii_redactor import redact_pii
from app.services.crisis_detector import detect_crisis
from app.services.audit_log import (
    log_conversation_turn,
    log_query_execution,
    log_crisis_detected,
    log_session_reset,
)

logger = logging.getLogger(__name__)

# Use LLM-based slot extraction when ANTHROPIC_API_KEY is available.
# Falls back to regex-only if the key is not set.
_USE_LLM_EXTRACTION = bool(os.getenv("ANTHROPIC_API_KEY"))

if _USE_LLM_EXTRACTION:
    from app.services.llm_slot_extractor import extract_slots_smart
    logger.info("LLM slot extraction enabled (ANTHROPIC_API_KEY found)")
else:
    logger.info("LLM slot extraction disabled — using regex only")


# ---------------------------------------------------------------------------
# MESSAGE CLASSIFICATION
# ---------------------------------------------------------------------------
# Lightweight keyword router that decides how to handle a message BEFORE
# touching the slot extractor. This keeps the conversation feeling natural
# without sending every "thanks" or "hi" through a DB query.

_RESET_PHRASES = [
    "start over", "reset", "clear", "new search", "begin again",
    "restart", "start again", "nevermind", "never mind",
]

# Short reset words that need exact-match to avoid false positives
# ("cancel" inside "I can't cancel my appointment" should not reset)
_RESET_EXACT = ["cancel"]

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
    "what services", "what other services", "what else",
    "what do you offer", "what can i search for",
    "list services", "show services", "available services",
]

_ESCALATION_PHRASES = [
    "peer navigator", "talk to a person", "talk to someone",
    "speak to someone", "speak to a person", "real person",
    "human", "connect me", "call someone", "live chat",
    "case manager", "social worker", "counselor",
]

# ---------------------------------------------------------------------------
# QUICK REPLY DEFINITIONS
# ---------------------------------------------------------------------------

# Welcome / entry-point category buttons (matches wireframe)
_WELCOME_QUICK_REPLIES = [
    {"label": "🍽️ Food", "value": "I need food"},
    {"label": "🏠 Shelter", "value": "I need shelter"},
    {"label": "🚿 Showers", "value": "I need a shower"},
    {"label": "👕 Clothing", "value": "I need clothing"},
    {"label": "🏥 Health Care", "value": "I need health care"},
    {"label": "💼 Jobs", "value": "I need help finding a job"},
    {"label": "⚖️ Legal Help", "value": "I need legal help"},
    {"label": "🧠 Mental Health", "value": "I need mental health support"},
    {"label": "📋 Other", "value": "I need other services"},
]

# Service-type labels for confirmation messages
_SERVICE_LABELS = {
    "food": "food",
    "shelter": "shelter",
    "clothing": "clothing",
    "personal_care": "showers / personal care",
    "medical": "health care",
    "mental_health": "mental health support",
    "legal": "legal help",
    "employment": "job help",
    "other": "other services",
}

# Confirmation-related phrases
# Short words that need EXACT match to avoid false positives
_CONFIRM_YES_EXACT = [
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "correct",
    "right", "go", "please", "do it", "find",
]

# Longer phrases that can use STARTS-WITH or CONTAINS matching
_CONFIRM_YES_STARTSWITH = [
    "yes ", "yeah ", "yep ", "sure ", "ok ",  # "yes search", "yes please", "yes I want to"
    "go ahead", "looks good", "looks right", "looks correct",
    "that's right", "thats right", "that's correct", "thats correct",
    "search for", "please search", "do the search",
    "yes search", "yes please",
    "confirm", "confirmed",
]

_CONFIRM_CHANGE_SERVICE = [
    "change service", "different service",
    "wrong service", "change what i need",
    "change service type",
]

_CONFIRM_CHANGE_LOCATION = [
    "change location", "different location", "wrong location",
    "different area", "different borough",
    "change borough", "change neighborhood",
]


def _classify_message(text: str) -> str:
    """
    Classify a message into a routing category.

    Returns one of:
        "crisis"           — suicide, violence, DV, trafficking, medical emergency
        "reset"            — user wants to start over
        "greeting"         — hi / hello / hey
        "thanks"           — thank you / thx
        "help"             — what can you do / how does this work
        "escalation"       — user wants to talk to a real person / peer navigator
        "confirm_yes"      — user confirmed a pending search
        "confirm_change_service"  — user wants to change service type
        "confirm_change_location" — user wants to change location
        "service"          — contains a service-related intent or slot data
        "general"          — everything else (conversational, follow-up, unclear)
    """
    lower = text.lower().strip()

    # Strip punctuation for matching
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # CRISIS — highest priority. Someone typing "I want to kill myself,
    # start over" MUST get crisis resources, not a session reset.
    crisis_result = detect_crisis(text)
    if crisis_result is not None:
        return "crisis"

    # Check reset (substring match for phrases, exact for short words)
    for phrase in _RESET_PHRASES:
        if phrase in cleaned:
            return "reset"
    for phrase in _RESET_EXACT:
        if cleaned == phrase:
            return "reset"

    # Check escalation — before greetings/thanks so "connect me with
    # a peer navigator please" doesn't fall through
    for phrase in _ESCALATION_PHRASES:
        if phrase in cleaned:
            return "escalation"

    # Check confirmation responses (only meaningful when pending_confirmation
    # is set, but we classify here and let the main flow decide)
    for phrase in _CONFIRM_CHANGE_SERVICE:
        if phrase in cleaned:
            return "confirm_change_service"

    for phrase in _CONFIRM_CHANGE_LOCATION:
        if phrase in cleaned:
            return "confirm_change_location"

    for phrase in _CONFIRM_YES_EXACT:
        if cleaned == phrase:
            return "confirm_yes"

    for phrase in _CONFIRM_YES_STARTSWITH:
        if cleaned.startswith(phrase) or cleaned == phrase:
            return "confirm_yes"

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

_ESCALATION_RESPONSE = (
    "I can connect you with a peer navigator who can help with your situation.\n\n"
    "You can reach the Streetlives team at:\n"
    "• Visit yourpeer.nyc and use the chat feature\n"
    "• Call 311 and ask for social services referrals\n\n"
    "If you're in crisis:\n"
    "• 988 Suicide & Crisis Lifeline — call or text 988\n"
    "• Crisis Text Line — text HOME to 741741\n\n"
    "Would you like me to keep searching for services, or is there "
    "anything else I can help with?"
)


# ---------------------------------------------------------------------------
# CONFIRMATION HELPERS
# ---------------------------------------------------------------------------

def _build_confirmation_message(slots: dict) -> str:
    """Build a human-readable confirmation prompt from filled slots."""
    service = slots.get("service_type", "services")
    service_label = _SERVICE_LABELS.get(service, service)
    location = slots.get("location", "your area")
    age = slots.get("age")

    parts = [f"I'll search for {service_label} in {location}"]
    if age:
        parts[0] += f" (age {age})"
    parts[0] += "."

    return " ".join(parts)


def _confirmation_quick_replies(slots: dict) -> list:
    """Quick-reply buttons for the confirmation step."""
    return [
        {"label": "✅ Yes, search", "value": "Yes, search"},
        {"label": "📍 Change location", "value": "Change location"},
        {"label": "🔄 Change service", "value": "Change service"},
        {"label": "❌ Start over", "value": "Start over"},
    ]


def _follow_up_quick_replies(slots: dict) -> list:
    """Quick-reply buttons for follow-up questions (when missing slots)."""
    if not slots.get("service_type"):
        return list(_WELCOME_QUICK_REPLIES)

    # Missing location — suggest common boroughs
    if not slots.get("location") or slots.get("location") == "__near_me__":
        return [
            {"label": "Manhattan", "value": "Manhattan"},
            {"label": "Brooklyn", "value": "Brooklyn"},
            {"label": "Queens", "value": "Queens"},
            {"label": "Bronx", "value": "Bronx"},
        ]

    return []

# Nearby borough suggestions for when a query returns no results
_NEARBY_BOROUGHS = {
    "Queens": ["Brooklyn", "Manhattan"],
    "Brooklyn": ["Manhattan", "Queens"],
    "Manhattan": ["Brooklyn", "Queens"],
    "Bronx": ["Manhattan", "Queens"],
    "Staten Island": ["Brooklyn", "Manhattan"],
    "New York": ["Brooklyn", "Queens"],  # Manhattan alias
}


def _no_results_message(slots: dict) -> str:
    """Helpful message when no services match the query."""
    service = slots.get("service_type", "services")
    location = slots.get("location", "your area")

    # Suggest nearby boroughs if we know the normalized city
    from app.rag.query_executor import normalize_location
    normalized = normalize_location(location) if location else None
    nearby = _NEARBY_BOROUGHS.get(normalized, [])

    parts = [
        f"I wasn't able to find {service} services in {location} "
        f"matching your criteria."
    ]

    if nearby:
        nearby_str = " or ".join(nearby[:2])
        parts.append(
            f"Would you like me to try {nearby_str} instead?"
        )
    else:
        parts.append(
            "You could try a different neighborhood or borough."
        )

    parts.append(
        'You can also say "connect with peer navigator" to talk to a real person.'
    )

    return " ".join(parts)


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

def _empty_reply(
    session_id: str,
    response: str,
    slots: dict,
    quick_replies: list | None = None,
) -> dict:
    """Build a reply dict with no service results."""
    return {
        "session_id": session_id,
        "response": response,
        "follow_up_needed": False,
        "slots": slots,
        "services": [],
        "result_count": 0,
        "relaxed_search": False,
        "quick_replies": quick_replies or [],
    }


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------

def generate_reply(message: str, session_id: str | None = None) -> dict:
    if not session_id:
        session_id = str(uuid.uuid4())

    # --- PII Redaction ---
    # Run redaction on every incoming message.
    # Slot extraction uses the ORIGINAL text (so locations/ages still parse).
    # The REDACTED version is what gets stored in session transcript.
    redacted_message, pii_detections = redact_pii(message)

    if pii_detections:
        logger.info(
            f"Session {session_id}: redacted {len(pii_detections)} PII item(s) "
            f"from message: {[d.pii_type for d in pii_detections]}"
        )

    existing = get_session_slots(session_id)
    category = _classify_message(message)  # classify on original for accuracy

    # --- Crisis ---
    # Highest priority. Crisis resources are shown immediately.
    # The session is NOT cleared — the user may continue afterward.
    if category == "crisis":
        crisis_result = detect_crisis(message)
        crisis_category, crisis_response = crisis_result
        logger.warning(
            f"Session {session_id}: crisis detected, "
            f"category='{crisis_category}'"
        )
        log_crisis_detected(session_id, crisis_category, redacted_message)
        result = _empty_reply(session_id, crisis_response, existing)
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Reset ---
    if category == "reset":
        clear_session(session_id)
        log_session_reset(session_id)
        result = _empty_reply(
            session_id, _RESET_RESPONSE, {},
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Greeting ---
    if category == "greeting":
        # If they have existing slots, acknowledge and re-offer
        if existing and any(v is not None for v in existing.values()):
            response = (
                "Hey again! I still have your earlier search info. "
                "Want to keep going, or would you like to start over?"
            )
            result = _empty_reply(session_id, response, existing)
        else:
            result = _empty_reply(
                session_id, _GREETING_RESPONSE, existing,
                quick_replies=list(_WELCOME_QUICK_REPLIES),
            )
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Thanks ---
    if category == "thanks":
        result = _empty_reply(
            session_id, _THANKS_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Help ---
    if category == "help":
        result = _empty_reply(
            session_id, _HELP_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Escalation ---
    if category == "escalation":
        result = _empty_reply(session_id, _ESCALATION_RESPONSE, existing)
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- Handle confirmation responses ---
    pending = existing.get("_pending_confirmation")

    if pending and category == "confirm_yes":
        # User confirmed — clear the flag and execute the query
        existing.pop("_pending_confirmation", None)
        save_session_slots(session_id, existing)
        result = _execute_and_respond(session_id, message, existing)
        _log_turn(session_id, redacted_message, result, category)
        return result

    if pending and category == "confirm_change_service":
        # User wants to change service type — clear it and ask
        existing.pop("_pending_confirmation", None)
        existing["service_type"] = None
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem! What kind of help do you need?",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category)
        return result

    if pending and category == "confirm_change_location":
        # User wants to change location — clear it and ask
        existing.pop("_pending_confirmation", None)
        existing["location"] = None
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "Sure! What neighborhood or borough should I search in?",
            existing,
            quick_replies=[
                {"label": "Manhattan", "value": "Manhattan"},
                {"label": "Brooklyn", "value": "Brooklyn"},
                {"label": "Queens", "value": "Queens"},
                {"label": "Bronx", "value": "Bronx"},
                {"label": "Staten Island", "value": "Staten Island"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category)
        return result

    # If pending confirmation but user typed something new (not a
    # confirmation action), check if it contains new slot data.
    # If not, gently re-show the confirmation rather than falling
    # through to general conversation (which causes loops).
    if pending:
        existing.pop("_pending_confirmation", None)

        # Check if the message has new slot data
        if _USE_LLM_EXTRACTION:
            pending_extracted = extract_slots_smart(message)
        else:
            pending_extracted = extract_slots(message)
        pending_has_new = any(v is not None for v in pending_extracted.values())

        if not pending_has_new:
            # No new slots — user is probably trying to confirm or is confused.
            # Re-show the confirmation with a nudge.
            existing["_pending_confirmation"] = True
            save_session_slots(session_id, existing)

            confirm_msg = (
                "Just to make sure — " + _build_confirmation_message(existing)
                + ' Tap "Yes, search" to go, or you can change the details.'
            )
            confirm_qr = _confirmation_quick_replies(existing)

            result = {
                "session_id": session_id,
                "response": confirm_msg,
                "follow_up_needed": True,
                "slots": existing,
                "services": [],
                "result_count": 0,
                "relaxed_search": False,
                "quick_replies": confirm_qr,
            }
            _log_turn(session_id, redacted_message, result, "confirmation_nudge")
            return result

        # Has new slot data — merge and re-process below

    # --- Service request or general conversation ---
    # Extract slots from ORIGINAL text (so "I'm 17 in Queens" still works).
    # Store the REDACTED version in the session transcript.
    if _USE_LLM_EXTRACTION:
        extracted = extract_slots_smart(message)
    else:
        extracted = extract_slots(message)

    # Track whether THIS message contributed any new slot data
    has_new_slots = any(v is not None for v in extracted.values())

    merged = merge_slots(existing, extracted)

    # Store the redacted message in transcript history (not the original)
    if "transcript" not in merged:
        merged["transcript"] = []
    merged["transcript"].append({"role": "user", "text": redacted_message})

    save_session_slots(session_id, merged)

    # If enough detail exists AND this message contributed new info,
    # go to CONFIRMATION step. If the user just typed "no" or something
    # conversational and the old slots happen to be complete, don't
    # re-trigger confirmation — route to general conversation instead.
    if is_enough_to_answer(merged) and has_new_slots:
        # Set pending confirmation flag
        merged["_pending_confirmation"] = True
        save_session_slots(session_id, merged)

        confirm_msg = _build_confirmation_message(merged)
        confirm_qr = _confirmation_quick_replies(merged)

        result = {
            "session_id": session_id,
            "response": confirm_msg,
            "follow_up_needed": True,
            "slots": merged,
            "services": [],
            "result_count": 0,
            "relaxed_search": False,
            "quick_replies": confirm_qr,
        }
        _log_turn(session_id, redacted_message, result, "confirmation")
        return result

    # Not enough slots yet — but is this a service request or just conversation?
    if category == "service":
        # They mentioned something service-related but we need more info
        follow_up = next_follow_up_question(merged)
        follow_up_qr = _follow_up_quick_replies(merged)
        result = {
            "session_id": session_id,
            "response": follow_up,
            "follow_up_needed": True,
            "slots": merged,
            "services": [],
            "result_count": 0,
            "relaxed_search": False,
            "quick_replies": follow_up_qr,
        }
        _log_turn(session_id, redacted_message, result, category)
        return result

    # --- General conversation ---
    # The message didn't match any service keywords and isn't a greeting/reset.
    # Use Gemini for a natural conversational response that gently steers
    # the user back toward telling us what they need.
    response = _fallback_response(message, merged)
    result = _empty_reply(
        session_id, response, merged,
        quick_replies=list(_WELCOME_QUICK_REPLIES),
    )
    _log_turn(session_id, redacted_message, result, "general")
    return result


# ---------------------------------------------------------------------------
# QUERY EXECUTION (after confirmation)
# ---------------------------------------------------------------------------

def _execute_and_respond(session_id: str, message: str, slots: dict) -> dict:
    """Execute the DB query and return results. Called after user confirms."""
    bot_response = None
    services_list = []
    result_count = 0
    relaxed = False

    try:
        results = query_services(
            service_type=slots.get("service_type"),
            location=slots.get("location"),
            age=slots.get("age"),
        )

        # Log the query execution
        log_query_execution(
            session_id=session_id,
            template_name=results.get("template_used", "unknown"),
            params=results.get("params_applied", {}),
            result_count=results.get("result_count", 0),
            relaxed=results.get("relaxed", False),
            execution_ms=results.get("execution_ms", 0),
        )

        if results.get("error"):
            logger.warning(f"Query error: {results['error']}")
            bot_response = _fallback_response(message, slots)

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
            bot_response = _no_results_message(slots)

    except Exception as e:
        logger.error(f"Database query failed: {e}")
        bot_response = _fallback_response(message, slots)

    if bot_response is None:
        bot_response = _fallback_response(message, slots)

    # After showing results, offer to search again
    after_results_qr = [
        {"label": "🔍 New search", "value": "Start over"},
        {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
    ]

    return {
        "session_id": session_id,
        "response": bot_response,
        "follow_up_needed": False,
        "slots": slots,
        "services": services_list,
        "result_count": result_count,
        "relaxed_search": relaxed,
        "quick_replies": after_results_qr if services_list else list(_WELCOME_QUICK_REPLIES),
    }


# ---------------------------------------------------------------------------
# AUDIT LOG HELPER
# ---------------------------------------------------------------------------

def _log_turn(session_id: str, user_msg: str, result: dict, category: str):
    """Log a conversation turn to the audit log."""
    try:
        log_conversation_turn(
            session_id=session_id,
            user_message_redacted=user_msg,
            bot_response=result.get("response", ""),
            slots=result.get("slots", {}),
            category=category,
            services_count=result.get("result_count", 0),
            quick_replies=result.get("quick_replies", []),
            follow_up_needed=result.get("follow_up_needed", False),
        )
    except Exception as e:
        logger.error(f"Failed to log conversation turn: {e}")
