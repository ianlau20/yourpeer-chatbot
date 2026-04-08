import uuid
import re
import os
import logging

from app.llm.claude_client import claude_reply
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
    NEAR_ME_SENTINEL,
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

# Use LLM-based features when ANTHROPIC_API_KEY is available.
# Falls back to regex-only if the key is not set.
_USE_LLM = bool(os.getenv("ANTHROPIC_API_KEY"))

if _USE_LLM:
    from app.services.llm_slot_extractor import extract_slots_smart
    from app.llm.claude_client import classify_message_llm
    logger.info("LLM features enabled (ANTHROPIC_API_KEY found)")
else:
    logger.info("LLM features disabled — using regex only")


# ---------------------------------------------------------------------------
# MESSAGE CLASSIFICATION
# ---------------------------------------------------------------------------
# Lightweight keyword router that decides how to handle a message BEFORE
# touching the slot extractor. This keeps the conversation feeling natural
# without sending every "thanks" or "hi" through a DB query.

_RESET_PHRASES = [
    "start over", "reset", "clear", "new search", "begin again",
    "restart", "start again", "nevermind", "never mind",
    "cancel my search", "please cancel", "i want to cancel",
    "cancel search", "cancel this",
]

# Short reset words that need exact-match to avoid false positives
# ("cancel" inside "I can't cancel my appointment" should not reset)
_RESET_EXACT = ["cancel"]

_GREETING_PHRASES = [
    "hi", "hey", "hello", "sup", "yo", "good morning", "good afternoon",
    "good evening", "whats up", "what's up",
]

_THANKS_PHRASES = [
    "thanks", "thank you", "appreciate it",
    "that helps", "perfect", "great thanks", "awesome",
]

# Short thanks words that need exact match to avoid substring collisions
# (e.g., "ty" in "city", "Port Authority"; "thx" unlikely to collide but safe)
_THANKS_EXACT = [
    "thx", "ty",
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

_FRUSTRATION_PHRASES = [
    "not helpful", "isn't helpful", "isnt helpful",
    "doesn't help", "doesnt help", "didn't help", "didnt help",
    "already tried", "tried that", "tried those",
    "none of those", "none of them", "doesn't work",
    "doesnt work", "didn't work", "didnt work",
    "useless", "waste of time", "not working",
    "can't find anything", "cant find anything",
    "not what i needed", "not what i need",
    "wrong results", "results are bad", "results are wrong",
    "thats not right", "that's not right", "thats wrong", "that's wrong",
    "not useful", "this sucks", "so unhelpful",
]

# Emotional expressions — sub-crisis distress that deserves warm
# acknowledgment rather than a service menu or a steer-back response.
# These must NOT overlap with service keywords ("feeling hungry" → service).
_EMOTIONAL_PHRASES = [
    "feeling down", "feeling really down",
    "feeling sad", "feeling really sad",
    "feeling bad", "feeling really bad",
    "feeling depressed", "so depressed",
    "feeling scared", "feeling really scared", "im scared", "i'm scared",
    "feeling anxious", "feeling really anxious", "so anxious",
    "feeling lonely", "feeling alone", "so lonely", "all alone",
    "feeling hopeless", "feel hopeless",
    "feeling lost", "i feel lost",
    "feeling stuck", "i feel stuck",
    "not doing well", "not doing good", "not doing ok", "not doing okay",
    "im not okay", "i'm not okay", "i'm not ok", "im not ok",
    "having a hard time", "having a rough time", "having a tough time",
    "rough day", "bad day", "tough day", "hard day",
    "stressed out", "so stressed", "really stressed",
    "i'm struggling", "im struggling",
    "tired of everything", "exhausted",
    "i just need someone to talk to", "just need to talk",
    "nobody cares", "no one cares",
]

_BOT_IDENTITY_PHRASES = [
    "are you a robot", "are you a bot", "are you ai",
    "are you a real person", "are you human",
    "am i talking to a person", "am i talking to a human",
    "is this a bot", "is this ai", "is this a chatbot",
    "is this a real person", "who am i talking to",
    "are you a computer", "are you a machine",
    "talking to a robot",
]

# Bot capability questions — asking HOW the bot works, not WHO it is.
_BOT_QUESTION_PHRASES = [
    "why can't you", "why cant you", "why couldn't you", "why couldnt you",
    "why didn't you", "why didnt you", "why weren't you", "why werent you",
    "how do you", "how does this work", "how does this bot work",
    "what can you do", "what can you search", "what can you help with",
    "what services do you", "what services can you",
    "can you search outside", "do you work outside",
    "can you explain", "can you tell me how",
    "why did you show", "why did you give",
    "what happened to", "what went wrong",
    # Privacy questions
    "is this private", "is this confidential", "is this safe",
    "is this anonymous", "are you recording",
    "who can see", "can anyone see", "do you share",
    "do you store", "do you save", "do you track",
    "can ice see", "can the police", "will this affect my",
    "can my case worker", "can my caseworker", "can the shelter see",
    "how do i delete", "how do i clear",
    "do you know who i am", "do you know my name",
]

# Confusion / overwhelm — the user doesn't know what they need.
# These MUST be caught before hitting the LLM, which would otherwise
# interpret "I don't know what to do" as a mental health request.
_CONFUSED_PHRASES = [
    "don't know what to do", "dont know what to do",
    "idk what to do", "i don't know", "i dont know",
    "not sure what i need", "don't know what i need",
    "dont know what i need", "what should i do",
    "don't know where to start", "dont know where to start",
    "i'm confused", "im confused",
    "i'm lost", "im lost",
    "i'm overwhelmed", "im overwhelmed",
    "i'm not sure", "im not sure",
    "where do i start", "where do i begin",
    "what are my options", "what can i do",
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

# Denial phrases — user declines the pending confirmation.
# Treated as a soft reset: clears pending confirmation and offers options.
_CONFIRM_DENY_EXACT = [
    "no", "nah", "nope", "not yet", "wait", "hold on", "stop",
]

_CONFIRM_DENY_PHRASES = [
    "no thanks", "no thank you", "i dont want", "i don't want",
    "not right now", "maybe later", "changed my mind",
    "i changed my mind",
]


def _classify_action(text: str) -> str | None:
    """Classify a message's action intent (what the user wants to DO).

    Returns one of the action categories or None if no action detected:
        "reset", "bot_identity", "bot_question", "escalation",
        "confirm_change_service", "confirm_change_location",
        "confirm_yes", "confirm_deny", "greeting", "thanks", "help"
    """
    lower = text.lower().strip()
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # Reset
    for phrase in _RESET_PHRASES:
        if phrase in cleaned:
            return "reset"
    for phrase in _RESET_EXACT:
        if cleaned == phrase:
            return "reset"

    # Bot identity
    for phrase in _BOT_IDENTITY_PHRASES:
        if phrase in cleaned:
            return "bot_identity"

    # Bot questions (including privacy)
    for phrase in _BOT_QUESTION_PHRASES:
        if phrase in cleaned:
            return "bot_question"

    # Escalation
    for phrase in _ESCALATION_PHRASES:
        if phrase in cleaned:
            return "escalation"

    # Confirmation actions
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
    for phrase in _CONFIRM_DENY_EXACT:
        if cleaned == phrase:
            return "confirm_deny"
    for phrase in _CONFIRM_DENY_PHRASES:
        if phrase in cleaned:
            return "confirm_deny"

    # Greeting (short messages only)
    if len(cleaned.split()) <= 3:
        for phrase in _GREETING_PHRASES:
            if cleaned == phrase or cleaned.startswith(phrase + " "):
                return "greeting"

    # Thanks (only if no continuation words)
    _has_continuation = any(w in cleaned for w in [
        "but", "however", "though", "need", "want", "also", "more",
    ])
    if not _has_continuation:
        for phrase in _THANKS_PHRASES:
            if phrase in cleaned:
                return "thanks"
        for phrase in _THANKS_EXACT:
            if cleaned == phrase:
                return "thanks"

    # Help
    for phrase in _HELP_PHRASES:
        if phrase in cleaned:
            return "help"

    return None


def _classify_tone(text: str) -> str | None:
    """Classify a message's emotional tone (how the user FEELS).

    No service-word gating — always runs. The caller decides how to
    combine tone with service intent.

    Returns one of: "crisis", "emotional", "frustrated", "confused", or None.
    """
    lower = text.lower().strip()
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # Crisis — highest priority
    crisis_result = detect_crisis(text)
    if crisis_result is not None:
        return "crisis"

    # Frustration
    for phrase in _FRUSTRATION_PHRASES:
        if phrase in cleaned:
            return "frustrated"

    # Emotional
    for phrase in _EMOTIONAL_PHRASES:
        if phrase in cleaned:
            return "emotional"

    # Confused
    for phrase in _CONFUSED_PHRASES:
        if phrase in cleaned:
            return "confused"

    return None


def _classify_message(text: str) -> str:
    """Classify a message into a single routing category.

    Thin wrapper that combines _classify_action() and _classify_tone()
    for backward compatibility with existing tests and the LLM fallback.

    The main routing in generate_reply() uses the split functions directly
    for more nuanced handling (e.g., service intent + emotional tone).
    """
    lower = text.lower().strip()
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # Crisis always wins
    crisis_result = detect_crisis(text)
    if crisis_result is not None:
        return "crisis"

    # Action intent
    action = _classify_action(text)
    if action:
        return action

    # Frustration (before slot check — "not helpful" is never a service request)
    for phrase in _FRUSTRATION_PHRASES:
        if phrase in cleaned:
            return "frustration"

    # Check slots — if service intent found, it wins over emotional/confused
    extracted = extract_slots(text)
    has_slot = any(v is not None for k, v in extracted.items()
                   if k != "additional_services")
    if has_slot:
        return "service"

    # Emotional / confused (only when no service intent)
    tone = _classify_tone(text)
    if tone == "emotional":
        return "emotional"
    if tone == "confused":
        return "confused"

    # LLM fallback for longer messages
    if _USE_LLM and len(cleaned.split()) > 3:
        llm_category = classify_message_llm(text)
        if llm_category is not None:
            logger.info(
                f"LLM classifier override: regex='general' → llm='{llm_category}'"
            )
            return llm_category

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

_FRUSTRATION_RESPONSE = (
    "I'm sorry this hasn't been what you needed. I understand how "
    "frustrating it can be when you've already tried places and they "
    "didn't work out.\n\n"
    "Here are some options:\n"
    "• I can search a different area or service type\n"
    "• I can connect you with a peer navigator who knows the system well\n"
    "• Call 311 for live social services help\n\n"
    "What would be most helpful for you right now?"
)

_BOT_IDENTITY_RESPONSE = (
    "I'm an AI assistant for YourPeer. I help you find free services in "
    "NYC — things like food, shelter, clothing, and more — using verified "
    "information from our database.\n\n"
    "I don't make up information. All the services I show you come from "
    "real locations that have been checked by people who've used them.\n\n"
    "If you'd like to talk to a real person, I can connect you with a "
    "peer navigator. Otherwise, just tell me what you need help with!"
)

_CONFUSED_RESPONSE = (
    "That's okay — you don't have to know exactly what you need. "
    "I can help you figure it out.\n\n"
    "Here are some things people often look for:\n"
    "• A meal or groceries\n"
    "• A place to stay tonight\n"
    "• A shower, clean clothes, or toiletries\n"
    "• A doctor or someone to talk to\n"
    "• Help with legal issues, a job, or benefits\n\n"
    "Tap any option below, or just tell me what's going on "
    "and I'll point you in the right direction."
)

_EMOTIONAL_RESPONSE = (
    "I hear you, and I'm sorry you're going through a difficult time. "
    "You don't have to have everything figured out right now.\n\n"
    "If you'd like to talk to someone who understands, I can connect you "
    "with a peer navigator — they're people who've been through similar "
    "situations and know the system well.\n\n"
    "Or if there's something practical I can help you find — like food, "
    "a place to stay, or a shower — just let me know. I'm here."
)


def _build_empathetic_prompt(user_message: str, slots: dict) -> str:
    """Prompt for emotionally-charged messages that aren't crisis-level."""
    slot_context = ""
    if slots:
        filled = {k: v for k, v in slots.items()
                  if v is not None and not k.startswith("_") and k != "transcript"}
        if filled:
            slot_context = f"\nContext from our conversation so far: {filled}\n"

    return (
        "You are YourPeer, a friendly assistant that helps people find "
        "free social services in New York City.\n\n"
        "The user has shared something emotional. Respond with warmth and "
        "empathy. Your job right now is to ACKNOWLEDGE their feeling, not "
        "to steer them toward services.\n\n"
        "Guidelines:\n"
        "- Lead with acknowledgment. Validate what they're feeling.\n"
        "- Do NOT list service categories or show a menu of options.\n"
        "- Do NOT give medical, psychological, legal, or financial advice.\n"
        "- Do NOT diagnose, suggest treatments, or minimize their experience.\n"
        "- Mention that you can connect them with a peer navigator if they "
        "want someone to talk to.\n"
        "- Gently let them know you're here if there's something practical "
        "you can help them find, but don't push it.\n"
        "- Keep your response to 2-3 sentences. Be genuine, not scripted.\n"
        f"{slot_context}"
        f"User message: {user_message}"
    )


# ---------------------------------------------------------------------------
# CONFIRMATION HELPERS
# ---------------------------------------------------------------------------

def _build_confirmation_message(slots: dict) -> str:
    """Build a human-readable confirmation prompt from filled slots.

    Slot values are redacted before echoing to prevent PII leakage
    (e.g. a street address captured as a location).
    """
    service = slots.get("service_type", "services")
    # Prefer the specific sub-type label (e.g. "dental care") over the
    # generic category label (e.g. "health care") when available.
    service_label = slots.get("service_detail") or _SERVICE_LABELS.get(service, service)
    location = slots.get("location", "your area")
    age = slots.get("age")

    # When using browser geolocation, show "near your location"
    # instead of the raw "__near_me__" sentinel.
    if (
        location == NEAR_ME_SENTINEL
        and slots.get("_latitude") is not None
    ):
        location = "near your location"
    else:
        # Redact any PII that may have been captured in slot values
        # (e.g. street addresses extracted as location)
        location, _ = redact_pii(location)

    parts = [f"I'll search for {service_label} {location}"]
    if age:
        parts[0] += f" (age {age})"

    family = slots.get("family_status")
    if family == "with_children":
        parts[0] += ", with children"
    elif family == "with_family":
        parts[0] += ", with family"
    elif family == "alone":
        parts[0] += ", for yourself"

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

    # Missing location — suggest common boroughs + geolocation option
    if not slots.get("location") or slots.get("location") == NEAR_ME_SENTINEL:
        return [
            {"label": "📍 Use my location", "value": "__use_geolocation__"},
            {"label": "Manhattan", "value": "Manhattan"},
            {"label": "Brooklyn", "value": "Brooklyn"},
            {"label": "Queens", "value": "Queens"},
            {"label": "Bronx", "value": "Bronx"},
        ]

    return []

# Borough suggestions when a query returns no results.
# Ordered by actual service availability from DB audit (Apr 2026),
# not just geographic proximity. Each service type lists boroughs
# from highest to lowest service count, excluding the user's own borough.
#
# Format: { service_type: { borough: [suggestion1, suggestion2] } }
# Falls back to _NEARBY_BOROUGHS_DEFAULT for unknown service types.

_NEARBY_BOROUGHS_BY_SERVICE = {
    "food": {
        "Manhattan":    ["Brooklyn", "Queens"],
        "Brooklyn":     ["Queens", "Bronx"],
        "Queens":       ["Brooklyn", "Bronx"],
        "Bronx":        ["Brooklyn", "Queens"],
        "Staten Island": ["Brooklyn", "Queens"],
    },
    "shelter": {
        # Shelter is thin everywhere — Manhattan has most (14), suggest it first
        "Manhattan":    ["Brooklyn", "Bronx"],
        "Brooklyn":     ["Manhattan", "Bronx"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
    "clothing": {
        # Manhattan-heavy (34). Queens only has 3 — always suggest Manhattan
        "Manhattan":    ["Brooklyn", "Bronx"],
        "Brooklyn":     ["Manhattan", "Bronx"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
    "personal_care": {
        # Shower: Manhattan (14), Bronx (5), Queens (4). Brooklyn only has 2
        "Manhattan":    ["Bronx", "Queens"],
        "Brooklyn":     ["Manhattan", "Bronx"],
        "Queens":       ["Manhattan", "Bronx"],
        "Bronx":        ["Manhattan", "Queens"],
        "Staten Island": ["Manhattan", "Queens"],
    },
    "medical": {
        # Health: Manhattan (237), Brooklyn (158), Bronx (118)
        "Manhattan":    ["Brooklyn", "Bronx"],
        "Brooklyn":     ["Manhattan", "Bronx"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
    "mental_health": {
        # Mental Health: Manhattan (40), Brooklyn (36), Queens (18)
        "Manhattan":    ["Brooklyn", "Queens"],
        "Brooklyn":     ["Manhattan", "Queens"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
    "legal": {
        # Legal: Manhattan (19), Brooklyn (9), Bronx (6)
        "Manhattan":    ["Brooklyn", "Bronx"],
        "Brooklyn":     ["Manhattan", "Bronx"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
    "employment": {
        # Employment: Manhattan (9), Brooklyn (6), Queens (2)
        "Manhattan":    ["Brooklyn", "Queens"],
        "Brooklyn":     ["Manhattan", "Queens"],
        "Queens":       ["Manhattan", "Brooklyn"],
        "Bronx":        ["Manhattan", "Brooklyn"],
        "Staten Island": ["Manhattan", "Brooklyn"],
    },
}

# Default fallback — geographic proximity when no service-specific data
_NEARBY_BOROUGHS_DEFAULT = {
    "Manhattan":    ["Brooklyn", "Queens"],
    "Brooklyn":     ["Manhattan", "Queens"],
    "Queens":       ["Brooklyn", "Manhattan"],
    "Bronx":        ["Manhattan", "Queens"],
    "Staten Island": ["Brooklyn", "Manhattan"],
    "New York":     ["Brooklyn", "Queens"],  # Manhattan alias
}

# Service types that map to each template key (mirrors SLOT_SERVICE_TO_TEMPLATE)
_SERVICE_TO_BOROUGH_KEY = {
    "food": "food",
    "shelter": "shelter", "housing": "shelter",
    "clothing": "clothing",
    "personal_care": "personal_care", "shower": "personal_care",
    "medical": "medical", "healthcare": "medical", "health": "medical",
    "mental_health": "mental_health",
    "legal": "legal",
    "employment": "employment", "job": "employment",
}


def _get_nearby_boroughs(service_type: str | None, borough: str) -> list[str]:
    """Return the best nearby boroughs to suggest for a given service + borough combo."""
    service_key = _SERVICE_TO_BOROUGH_KEY.get((service_type or "").lower())
    if service_key and service_key in _NEARBY_BOROUGHS_BY_SERVICE:
        return _NEARBY_BOROUGHS_BY_SERVICE[service_key].get(borough, [])
    return _NEARBY_BOROUGHS_DEFAULT.get(borough, [])


def _no_results_message(slots: dict) -> str:
    """Helpful message when no services match the query."""
    service = slots.get("service_type", "services")
    location = slots.get("location", "your area")

    from app.rag.query_executor import normalize_location, is_borough
    normalized = normalize_location(location) if location else None

    # Only suggest nearby boroughs if the user searched at the borough level
    nearby = []
    if normalized and is_borough(location):
        nearby = _get_nearby_boroughs(service, normalized)

    parts = [
        f"I wasn't able to find {service} services in {location} "
        f"matching your criteria."
    ]

    if nearby:
        nearby_str = " or ".join(nearby[:2])
        parts.append(f"Would you like me to try {nearby_str} instead?")
    else:
        parts.append("You could try a different neighborhood or borough.")

    parts.append(
        'You can also say "connect with peer navigator" to talk to a real person.'
    )

    return " ".join(parts)


def _build_conversational_prompt(user_message: str, slots: dict) -> str:
    """Prompt for general conversational messages that aren't service queries.

    Two modes:
    - If the user has partially filled slots (service intent detected earlier),
      gently steer them back to completing the search.
    - If no service intent yet, just be present and warm. Don't push services.
    """
    # Check if there's an active service search in progress
    filled = {k: v for k, v in (slots or {}).items()
              if v is not None and not k.startswith("_") and k != "transcript"}
    has_service_intent = bool(filled.get("service_type") or filled.get("location"))

    slot_context = ""
    if filled:
        slot_context = f"\nContext from our conversation so far: {filled}\n"

    steer_instruction = (
        "The user has already expressed a service need. Gently remind them "
        "you can continue their search, or ask if they'd like to change what "
        "they're looking for. Don't be pushy — just a brief mention."
        if has_service_intent
        else
        "The user has NOT expressed a service need yet. Do NOT push services "
        "or list categories. Just respond naturally. If the conversation "
        "feels right, you can mention that you're here to help find services "
        "whenever they're ready, but only as a brief aside, not the focus."
    )

    return (
        "You are YourPeer, a friendly assistant that helps people find "
        "free social services in New York City.\n"
        "You are warm, respectful, and concise.\n\n"
        "STRICT RULES:\n"
        "- You do NOT make up service names, addresses, or phone numbers.\n"
        "- You do NOT give specific medical, legal, psychological, or "
        "financial advice.\n"
        "- You do NOT diagnose conditions or suggest treatments.\n"
        "- You do NOT make promises about service availability.\n"
        "- You do NOT encourage specific life decisions.\n"
        "- If someone needs professional guidance, suggest they talk to a "
        "peer navigator.\n\n"
        f"{steer_instruction}\n"
        "Keep your response to 1-3 sentences.\n"
        f"{slot_context}"
        f"User message: {user_message}"
    )


def _build_bot_question_prompt(user_message: str, slots: dict = None) -> str:
    """Prompt for questions about the bot's capabilities or behavior."""
    # Build context about what's happened in the session so far
    context_lines = []
    if slots:
        if slots.get("service_type"):
            context_lines.append(
                f"- The user is currently searching for: {slots.get('service_type')}"
            )
        if slots.get("location"):
            context_lines.append(
                f"- Their location is set to: {slots.get('location')}"
            )
        if slots.get("_latitude") is not None:
            context_lines.append(
                "- The user has shared their browser geolocation"
            )

    context_section = ""
    if context_lines:
        context_section = (
            "Current session context:\n"
            + "\n".join(context_lines)
            + "\n\n"
        )

    return (
        "You are YourPeer, a friendly assistant that helps people find "
        "free social services in New York City.\n\n"
        "The user is asking a question about how you work or what you can do. "
        "Answer their SPECIFIC question directly and honestly. Do not give a "
        "generic overview unless they asked for one.\n\n"
        f"{context_section}"
        "Facts about yourself:\n"
        "- You search a database of verified social services in NYC's five "
        "boroughs, maintained by Streetlives (yourpeer.nyc)\n"
        "- You ONLY cover New York City. You cannot search outside the five "
        "boroughs (Manhattan, Brooklyn, Queens, Bronx, Staten Island). If "
        "someone needs services elsewhere, suggest calling 211\n"
        "- Service categories you can search:\n"
        "  • Food: soup kitchens, food pantries, groceries\n"
        "  • Shelter: emergency shelter, transitional housing\n"
        "  • Clothing: free clothing programs\n"
        "  • Personal care: showers, laundry, haircuts\n"
        "  • Health care: medical, dental, vision, STD testing, vaccinations\n"
        "  • Mental health: counseling, therapy, substance abuse, AA/NA\n"
        "  • Legal help: immigration, eviction, asylum\n"
        "  • Jobs: employment programs, job training, resume help\n"
        "  • Other: benefits (SNAP/EBT/Medicaid), IDs, drop-in centers, "
        "case workers, free wifi, mail services, transit help\n"
        "- Geolocation: you use the browser's GPS when the user taps "
        "'Use my location'. Common reasons it can fail:\n"
        "  • The user denied the browser permission prompt\n"
        "  • They're on a device/browser that doesn't support geolocation\n"
        "  • GPS timed out (e.g., indoors with weak signal)\n"
        "  • The site isn't served over HTTPS\n"
        "  If geolocation fails, you ask for a neighborhood or borough instead\n"
        "- Privacy: you don't store personal information. Conversations are "
        "private and not linked to any identity. Specifics:\n"
        "  • You are NOT connected to any government agency, including ICE\n"
        "  • You do NOT share information with law enforcement\n"
        "  • Shelters, case workers, and providers cannot see the conversation\n"
        "  • Using this chat will NOT affect benefits or case status\n"
        "  • If a user shares PII by accident, it's automatically redacted\n"
        "  • Saying 'start over' clears the session immediately\n"
        "  • Chat history on the device auto-expires after 30 minutes\n"
        "  • On shared/public devices, other users could potentially see "
        "the chat until it expires\n"
        "- You can connect users with a human peer navigator for support\n"
        "- You are an AI assistant, not a human\n"
        "- Your data comes from verified listings. Hours and availability may "
        "change — always call ahead to confirm\n\n"
        "Keep your response to 2-3 sentences. Answer the specific question. "
        "Be honest about limitations.\n\n"
        f"User question: {user_message}"
    )


def _static_bot_answer(message: str) -> str:
    """Pattern-matched answers for common bot questions when LLM is unavailable."""
    lower = message.lower()

    # Geolocation questions
    if any(w in lower for w in ["location", "gps", "geolocation", "find me", "where i am"]):
        if any(w in lower for w in ["why", "couldn't", "couldnt", "can't", "cant", "didn't", "didnt", "fail", "wrong"]):
            return (
                "Location access can fail for a few reasons: you may have "
                "denied the browser permission, your device might not support "
                "GPS, or the signal timed out (common indoors). You can always "
                "tell me your neighborhood or borough instead."
            )
        return (
            "When you tap 'Use my location', I ask your browser for GPS "
            "coordinates to find services nearby. If that doesn't work, "
            "just tell me your neighborhood or borough."
        )

    # Coverage / outside NYC
    if any(w in lower for w in ["outside", "other city", "other state", "new jersey", "nj", "outside nyc"]):
        return (
            "I only search within New York City's five boroughs. For services "
            "outside NYC, you can call 211 — it's a free helpline that "
            "connects people to local resources anywhere in the US."
        )

    # What services / categories
    if any(w in lower for w in ["what services", "what can you search", "what can you find", "what kind"]):
        return (
            "I can search for food (pantries, soup kitchens), shelter, "
            "clothing, showers & personal care, health care (medical, dental, "
            "vision), mental health (counseling, substance abuse), legal help "
            "(immigration, eviction), jobs, and other services like benefits, "
            "IDs, and drop-in centers."
        )

    # Privacy — immigration / law enforcement fears
    if any(w in lower for w in ["ice", "immigration", "deport", "undocumented", "immigrant"]):
        return (
            "I don't collect any identifying information — no name, no "
            "address, no immigration status. I'm not connected to any "
            "government agency, including ICE. Your conversation is "
            "anonymous and is not shared with anyone."
        )

    if any(w in lower for w in ["police", "cop", "law enforcement", "report", "arrest"]):
        return (
            "I don't share any information with law enforcement. I don't "
            "know who you are, and your conversation here is anonymous. "
            "The only exception is if you're in immediate danger — I'll "
            "share crisis hotline numbers, but that's your choice to call."
        )

    # Privacy — benefits / provider visibility
    if any(w in lower for w in ["benefits", "case worker", "caseworker", "shelter see", "affect my"]):
        return (
            "Using this chat won't affect your benefits or case status. "
            "Shelters, case workers, and service providers can't see your "
            "conversation here. I just help you find services — I don't "
            "report anything to anyone."
        )

    # Privacy — who can see / recording / sharing
    if any(w in lower for w in [
        "who can see", "anyone see", "see what i", "see my",
        "recording", "record", "listening",
        "share", "sharing", "shared with", "tell anyone",
    ]):
        return (
            "No one else can see your conversation. I don't record audio "
            "or share your messages with other people or organizations. "
            "If you're on a shared device, you can say 'start over' to "
            "clear the chat history."
        )

    # Privacy — delete / clear data
    if any(w in lower for w in ["delete", "clear", "erase", "remove my", "forget"]):
        return (
            "Say 'start over' and your session will be cleared immediately. "
            "On this device, your chat history is stored temporarily in your "
            "browser and auto-expires after 30 minutes of inactivity."
        )

    # Privacy — identity / anonymity
    if any(w in lower for w in ["know my name", "know who i am", "anonymous", "identify"]):
        return (
            "I don't know who you are. I don't ask for or store your name, "
            "phone number, or any personal details. If you share personal "
            "info by accident, it's automatically removed before anything "
            "is saved."
        )

    # Privacy — general
    if any(w in lower for w in ["private", "privacy", "data", "store", "save", "track",
                                 "safe to", "confidential", "secure", "trust"]):
        return (
            "Your conversations are private and anonymous. I don't store "
            "personal information or link conversations to any identity. "
            "I'm not connected to any government agency or service provider. "
            "You can say 'start over' at any time to clear your session."
        )

    # How does it work
    if any(w in lower for w in ["how do you work", "how does this work", "how does it work"]):
        return (
            "You tell me what you need and where you are, and I search a "
            "database of verified social services in NYC maintained by "
            "Streetlives. I'll show you matching services with addresses, "
            "hours, and phone numbers."
        )

    # Default generic answer
    return (
        "I search a database of verified social services across NYC's five "
        "boroughs — food, shelter, clothing, showers, health care, mental "
        "health, legal help, jobs, and more. Just tell me what you need "
        "and your neighborhood, and I'll find options for you."
    )


def _fallback_response(message: str, slots: dict) -> str:
    """Try Claude for conversational response, with a safe static fallback."""
    try:
        prompt = _build_conversational_prompt(message, slots)
        return claude_reply(prompt)
    except Exception as e:
        logger.error(f"Claude fallback also failed: {e}")
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

def generate_reply(
    message: str,
    session_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    request_id: str | None = None,
) -> dict:
    # Session ID is validated upstream by the chat route (signed token
    # check).  If somehow called without a session_id, generate a plain
    # UUID as a fallback — but the route should always provide one.
    if not session_id:
        session_id = str(uuid.uuid4())

    if not request_id:
        request_id = str(uuid.uuid4())

    logger.info(f"[req:{request_id}] Session {session_id}: processing message")

    # --- Empty message guard ---
    if not message or not message.strip():
        return _empty_reply(
            session_id,
            "What are you looking for today? I can help with food, "
            "shelter, clothing, health care, and more.",
            get_session_slots(session_id),
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )

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

    # Store browser geolocation coords in session if provided
    has_coords = latitude is not None and longitude is not None
    if has_coords:
        existing["_latitude"] = latitude
        existing["_longitude"] = longitude
        save_session_slots(session_id, existing)

    # --- EXTRACT SLOTS FIRST (before classification) ---
    # This is the key architectural change: slots are always extracted
    # so we know if there's service intent before deciding how to route.
    # Regex only here — LLM extraction runs later for complex messages.
    early_extracted = extract_slots(message)
    has_service_intent = early_extracted.get("service_type") is not None

    # --- CLASSIFY ACTION + TONE SEPARATELY ---
    action = _classify_action(message)
    tone = _classify_tone(message)

    # --- COMBINE INTO ROUTING CATEGORY ---
    # Priority: crisis > reset > confirmations > service intent > actions > tone > LLM > general
    #
    # The key insight: when service intent is present, it wins over
    # help/escalation/emotional/confused — those become tone modifiers
    # on the service flow, not separate routes.
    _response_tone = tone  # stored for use in service flow framing

    if tone == "crisis":
        category = "crisis"
    elif action == "reset":
        category = "reset"
    elif action in ("confirm_change_service", "confirm_change_location",
                     "confirm_yes", "confirm_deny"):
        category = action
    elif action in ("bot_identity", "bot_question", "greeting", "thanks"):
        category = action
    elif has_service_intent:
        # Service intent wins — help/escalation/emotional/confused become
        # tone modifiers, not separate routes. This replaces the ad-hoc
        # guards that used to re-check slots inside help/escalation handlers.
        category = "service"
    elif action == "help":
        category = "help"
    elif action == "escalation":
        category = "escalation"
    elif tone == "frustrated":
        category = "frustration"
    elif tone == "emotional":
        category = "emotional"
    elif tone == "confused":
        category = "confused"
    elif _USE_LLM and len(message.strip().split()) > 3:
        llm_category = classify_message_llm(message)
        if llm_category is not None:
            logger.info(
                f"LLM classifier override: regex='general' → llm='{llm_category}'"
            )
            category = llm_category
        else:
            category = "general"
    else:
        category = "general"

    # --- Crisis ---
    # Highest priority. Crisis resources are shown immediately.
    # The session is NOT cleared — the user may continue afterward.
    if category == "crisis":
        crisis_result = detect_crisis(message)
        if crisis_result is None:
            # Classification said crisis but detect_crisis disagrees
            # (e.g. LLM fail-open during classification but not during
            # the dedicated check). Treat as general conversation.
            category = "general"
        else:
            crisis_category, crisis_response = crisis_result
            logger.warning(
                f"Session {session_id}: crisis detected, "
                f"category='{crisis_category}'"
            )
            log_crisis_detected(session_id, crisis_category, redacted_message, request_id=request_id)
            # Clear any pending confirmation — a user in crisis shouldn't
            # return to a search confirmation on their next message.
            if existing.get("_pending_confirmation"):
                existing.pop("_pending_confirmation", None)
                save_session_slots(session_id, existing)
            result = _empty_reply(session_id, crisis_response, existing)
            _log_turn(session_id, redacted_message, result, category, request_id=request_id)
            return result

    # --- Reset ---
    if category == "reset":
        clear_session(session_id)
        log_session_reset(session_id)
        result = _empty_reply(
            session_id, _RESET_RESPONSE, {},
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Thanks ---
    if category == "thanks":
        result = _empty_reply(
            session_id, _THANKS_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Help ---
    if category == "help":
        # No ad-hoc slot guard needed — if the message had service intent,
        # it was already routed to "service" category above.
        result = _empty_reply(
            session_id, _HELP_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Bot Identity ---
    if category == "bot_identity":
        result = _empty_reply(
            session_id, _BOT_IDENTITY_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Bot capability questions ---
    # "Why couldn't you get my location?", "What can you search for?"
    # Answer directly using LLM with a factual prompt about capabilities.
    if category == "bot_question":
        if _USE_LLM:
            try:
                prompt = _build_bot_question_prompt(message, slots=existing)
                response = claude_reply(prompt)
            except Exception as e:
                logger.error(f"Bot question LLM response failed: {e}")
                response = _static_bot_answer(message)
        else:
            response = _static_bot_answer(message)
        result = _empty_reply(session_id, response, existing)
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Confused / Overwhelmed ---
    # "I don't know what to do", "I'm lost", "I'm overwhelmed"
    # Show gentle guidance with category buttons — do NOT send to LLM
    # (which would misinterpret as a mental health request).
    if category == "confused":
        existing["_last_action"] = "confused"
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id, _CONFUSED_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES) + [
                {"label": "🤝 Talk to a person", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Emotional expression ---
    # "I'm feeling really down", "having a rough day", "I'm scared"
    # Acknowledge the feeling warmly. Don't show service buttons unless
    # the user asks for something practical.
    if category == "emotional":
        if _USE_LLM:
            try:
                prompt = _build_empathetic_prompt(message, existing)
                response = claude_reply(prompt)
            except Exception as e:
                logger.error(f"Empathetic LLM response failed: {e}")
                response = _EMOTIONAL_RESPONSE
        else:
            response = _EMOTIONAL_RESPONSE

        # Track so "yes"/"no" on the next message refers to the peer
        # navigator offer, not a pending search confirmation.
        existing["_last_action"] = "emotional"
        save_session_slots(session_id, existing)

        result = _empty_reply(
            session_id, response, existing,
            quick_replies=[
                {"label": "🤝 Talk to a person", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Frustration ---
    if category == "frustration":
        already_frustrated = existing.get("_last_action") == "frustration"
        existing["_last_action"] = "frustration"
        save_session_slots(session_id, existing)

        if already_frustrated:
            # Repeated frustration — don't show the same wall of text.
            # Keep it short, acknowledge we're not helping, push navigator.
            result = _empty_reply(
                session_id,
                "I hear you — I'm clearly not finding what you need right now. "
                "I think a peer navigator would be more helpful. They're real "
                "people who know the system and can work with you directly. "
                "You can also call 311 for live help anytime.",
                existing,
                quick_replies=[
                    {"label": "🤝 Talk to a person", "value": "Connect with peer navigator"},
                    {"label": "🔄 Start over", "value": "Start over"},
                ],
            )
        else:
            result = _empty_reply(
                session_id, _FRUSTRATION_RESPONSE, existing,
                quick_replies=[
                    {"label": "🔍 Try different search", "value": "Start over"},
                    {"label": "👤 Peer navigator", "value": "connect me with a peer navigator"},
                ],
            )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Escalation ---
    if category == "escalation":
        # No ad-hoc slot guard needed — if the message had service intent
        # (e.g., outreach worker with "shelter in East Harlem"), it was
        # already routed to "service" category above.
        if existing.get("_pending_confirmation"):
            existing.pop("_pending_confirmation", None)
        existing["_last_action"] = "escalation"
        save_session_slots(session_id, existing)
        result = _empty_reply(session_id, _ESCALATION_RESPONSE, existing)
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- Context-aware "yes" / "no" handling ---
    # After an escalation or emotional response, "yes" and "no" refer to the
    # peer navigator offer — not to a pending search confirmation.
    last_action = existing.get("_last_action")

    if last_action in ("escalation", "emotional") and category == "confirm_yes":
        # "Yes" after escalation or emotional = "yes, connect me with a person"
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(session_id, _ESCALATION_RESPONSE, existing)
        _log_turn(session_id, redacted_message, result, "escalation", request_id=request_id)
        return result

    if last_action == "confused" and category == "confirm_yes":
        # "Yes" after confused = "yes, connect me with a person"
        # (the confused handler shows a "Talk to a person" button)
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(session_id, _ESCALATION_RESPONSE, existing)
        _log_turn(session_id, redacted_message, result, "escalation", request_id=request_id)
        return result

    if last_action == "frustration" and category == "confirm_yes":
        # "Yes" after frustration = "yes, start a new search"
        # (the frustration handler shows "Try different search" button)
        existing.pop("_last_action", None)
        clear_session(session_id)
        log_session_reset(session_id)
        result = _empty_reply(
            session_id, _RESET_RESPONSE, {},
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, "reset", request_id=request_id)
        return result

    if category == "confirm_deny" and last_action == "escalation":
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem — I'm here if you change your mind. "
            "Is there anything else I can help you with?",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id)
        return result

    if category == "confirm_deny" and last_action == "emotional":
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "That's okay. I'm here whenever you're ready. "
            "If there's anything practical I can help you find, just let me know.",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id)
        return result

    if category == "confirm_deny" and last_action in ("frustrated", "frustration"):
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No worries. If you'd like to try something else or talk to a "
            "real person, just let me know.",
            existing,
            quick_replies=[
                {"label": "🤝 Talk to a person", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id)
        return result

    if category == "confirm_deny" and last_action == "confused":
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "That's okay — no rush. I'm here when you're ready. "
            "You can also talk to a real person if that would help.",
            existing,
            quick_replies=[
                {"label": "🤝 Talk to a person", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id)
        return result

    # Clear the last_action tracker now that we've checked it
    if last_action:
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)

    # --- Handle confirmation responses ---
    pending = existing.get("_pending_confirmation")

    if pending and category == "confirm_yes":
        # User confirmed — clear the flag and execute the query
        existing.pop("_pending_confirmation", None)
        save_session_slots(session_id, existing)
        result = _execute_and_respond(session_id, message, existing, request_id=request_id)
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    if pending and category == "confirm_change_service":
        # User wants to change service type — clear it and ask
        existing.pop("_pending_confirmation", None)
        existing["service_type"] = None
        existing.pop("service_detail", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem! What kind of help do you need?",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    if pending and category == "confirm_deny":
        # User declined the search — clear confirmation, keep slots,
        # and offer options so they're not stuck in a loop.
        existing.pop("_pending_confirmation", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem! I'll hold onto your info in case you want to "
            "come back to it. What would you like to do?",
            existing,
            quick_replies=[
                {"label": "🔄 Change service", "value": "Change service"},
                {"label": "📍 Change location", "value": "Change location"},
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # If pending confirmation but user typed something new (not a
    # confirmation action), check if it contains new slot data.
    # If not, gently re-show the confirmation rather than falling
    # through to general conversation (which causes loops).
    if pending:
        existing.pop("_pending_confirmation", None)

        # Check if the message has new slot data
        if _USE_LLM:
            pending_extracted = extract_slots_smart(
                message,
                conversation_history=existing.get("transcript", []),
            )
        else:
            pending_extracted = extract_slots(message)
        pending_has_new = any(v is not None for k, v in pending_extracted.items()
                              if k != "additional_services")

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
            _log_turn(session_id, redacted_message, result, "confirmation_nudge", request_id=request_id)
            return result

        # Has new slot data — merge and re-process below

    # --- Service request or general conversation ---
    # Slots were already extracted with regex above (early_extracted).
    # For service-category messages, re-extract with LLM for better
    # accuracy on complex inputs. For non-service categories, use the
    # regex result to avoid LLM hallucinating slots from conversation history.
    if _USE_LLM and category == "service":
        extracted = extract_slots_smart(
            message,
            conversation_history=existing.get("transcript", []),
        )
    else:
        extracted = early_extracted

    # Track whether THIS message contributed any new slot data
    has_new_slots = any(v is not None for k, v in extracted.items()
                        if k != "additional_services")

    merged = merge_slots(existing, extracted)

    # Store the redacted message in transcript history (not the original)
    if "transcript" not in merged:
        merged["transcript"] = []
    merged["transcript"].append({"role": "user", "text": redacted_message})

    save_session_slots(session_id, merged)

    # Geolocation: if location is "near me" but we have browser coords,
    # that's enough to run a proximity search.
    _has_session_coords = (
        merged.get("_latitude") is not None
        and merged.get("_longitude") is not None
    )
    _geolocation_ready = (
        bool(merged.get("service_type"))
        and merged.get("location") == NEAR_ME_SENTINEL
        and _has_session_coords
    )

    # Build tone-based prefix for empathetic framing when the user
    # expressed emotion alongside a service request.
    _tone_prefix = ""
    if _response_tone == "emotional" and has_service_intent:
        _tone_prefix = "I hear you, and I want to help. "
    elif _response_tone == "frustrated" and has_service_intent:
        _tone_prefix = "I understand this has been frustrating. Let me try something different. "
    elif _response_tone == "confused" and has_service_intent:
        _tone_prefix = "No worries — let me help you with that. "

    # If enough detail exists AND this message contributed new info,
    # go to CONFIRMATION step.
    if (is_enough_to_answer(merged) or _geolocation_ready) and has_new_slots:
        # Set pending confirmation flag
        merged["_pending_confirmation"] = True
        save_session_slots(session_id, merged)

        confirm_msg = _tone_prefix + _build_confirmation_message(merged)
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
        _log_turn(session_id, redacted_message, result, "confirmation", request_id=request_id)
        return result

    # Not enough slots yet — but is this a service request or just conversation?
    if category == "service":
        # They mentioned something service-related but we need more info
        follow_up = _tone_prefix + next_follow_up_question(merged)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id)
        return result

    # --- General conversation ---
    # The message didn't match any service keywords and isn't a greeting/reset.

    # If the user has a location but no service_type and we already asked
    # what they need, they may have requested something we can't help with
    # (e.g. "helicopter ride"). Redirect gracefully to real services.
    if (merged.get("location")
            and not merged.get("service_type")
            and len(merged.get("transcript", [])) >= 2):
        location_label = merged["location"]
        result = _empty_reply(
            session_id,
            "I'm not sure I can help with that specifically, but I can "
            f"search for services in {location_label} — things like food, "
            "shelter, clothing, showers, health care, legal help, and more. "
            "What would be most helpful?",
            merged,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, "unrecognized_service", request_id=request_id)
        return result

    # Use Claude Haiku for a natural conversational response.
    # Don't push service category buttons — they were shown on welcome.
    # The user can say "what can you help with" to see them again.
    response = _fallback_response(message, merged)
    has_service_intent = bool(
        merged.get("service_type") or merged.get("location")
    )
    result = _empty_reply(
        session_id, response, merged,
        # Only show welcome buttons if the user hasn't started a search yet
        # and hasn't had multiple conversational turns (avoid being pushy).
        quick_replies=(
            list(_WELCOME_QUICK_REPLIES)
            if not has_service_intent and len(merged.get("transcript", [])) <= 1
            else []
        ),
    )
    _log_turn(session_id, redacted_message, result, "general", request_id=request_id)
    return result


# ---------------------------------------------------------------------------
# QUERY EXECUTION (after confirmation)
# ---------------------------------------------------------------------------

def _execute_and_respond(session_id: str, message: str, slots: dict, request_id: str | None = None) -> dict:
    """Execute the DB query and return results. Called after user confirms."""
    bot_response = None
    services_list = []
    result_count = 0
    relaxed = False

    try:
        # Only use browser geolocation coordinates when the user chose
        # "Use my location" (near-me sentinel).  If they typed a text
        # location like "Midtown East", the coordinates from a prior
        # near-me request must NOT override the text location.
        location = slots.get("location")
        use_coords = (
            location == NEAR_ME_SENTINEL
            and slots.get("_latitude") is not None
            and slots.get("_longitude") is not None
        )

        results = query_services(
            service_type=slots.get("service_type"),
            location=location,
            age=slots.get("age"),
            latitude=slots.get("_latitude") if use_coords else None,
            longitude=slots.get("_longitude") if use_coords else None,
            family_status=slots.get("family_status"),
        )

        # Log the query execution
        log_query_execution(
            session_id=session_id,
            template_name=results.get("template_used", "unknown"),
            params=results.get("params_applied", {}),
            result_count=results.get("result_count", 0),
            relaxed=results.get("relaxed", False),
            execution_ms=results.get("execution_ms", 0),
            freshness=results.get("freshness"),
            request_id=request_id,
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

def _log_turn(session_id: str, user_msg: str, result: dict, category: str, request_id: str | None = None):
    """Log a conversation turn to the audit log."""
    try:
        bot_response_redacted, _ = redact_pii(result.get("response", ""))
        log_conversation_turn(
            session_id=session_id,
            user_message_redacted=user_msg,
            bot_response=bot_response_redacted,
            slots=result.get("slots", {}),
            category=category,
            services_count=result.get("result_count", 0),
            quick_replies=result.get("quick_replies", []),
            follow_up_needed=result.get("follow_up_needed", False),
            request_id=request_id,
        )
    except Exception as e:
        logger.error(f"Failed to log conversation turn: {e}")
