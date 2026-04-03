"""
LLM-Based Slot Extractor

Uses Claude function calling to extract structured intake slots from
natural language. Uses a complexity-based routing strategy:

    1. Run regex extraction (fast, free)
    2. Check if the message is "simple" — short, clear keyword match,
       known location, no ambiguity
    3. SIMPLE → trust regex (skip LLM, saves ~1-2s and ~$0.001)
    4. COMPLEX → call LLM (longer messages, implicit needs, slang,
       multi-part sentences, conflicting signals)

This ensures the LLM handles nuanced inputs that regex gets wrong:
    - "I just got out of the hospital and need a place to stay" → shelter
    - "I'm in Queens but looking for food in the Bronx" → Bronx
    - "my son is 12 and needs a coat" → age=12
    - "somewhere safe for tonight, I'm a woman" → shelter + urgency
    - "I was just released from Rikers" → shelter
"""

import os
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import Anthropic SDK
try:
    import anthropic
    _anthropic_available = True
except ImportError:
    _anthropic_available = False
    logger.warning("anthropic SDK not installed — LLM slot extraction disabled")

# Lazy-initialized client
_client = None
_init_error = None


def _get_client():
    """Lazy-initialize the Anthropic client."""
    global _client, _init_error

    if _client is not None:
        return _client
    if _init_error is not None:
        raise _init_error
    if not _anthropic_available:
        _init_error = RuntimeError("anthropic SDK not installed")
        raise _init_error

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        _init_error = RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file."
        )
        raise _init_error

    try:
        _client = anthropic.Anthropic(api_key=api_key)
        return _client
    except Exception as e:
        _init_error = RuntimeError(f"Failed to initialize Anthropic client: {e}")
        raise _init_error


# ---------------------------------------------------------------------------
# TOOL DEFINITION
# ---------------------------------------------------------------------------
# Claude function calling schema for slot extraction.

_EXTRACT_SLOTS_TOOL = {
    "name": "extract_intake_slots",
    "description": (
        "Extract structured service request information from a user's message. "
        "The user is seeking free social services in New York City."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "service_type": {
                "type": "string",
                "enum": [
                    "food", "shelter", "clothing", "personal_care",
                    "medical", "mental_health", "legal", "employment", "other",
                ],
                "description": (
                    "The type of service the user is looking for. "
                    "food = meals, pantries, groceries. "
                    "shelter = housing, place to sleep, drop-in centers, "
                    "somewhere safe, transitional housing. "
                    "clothing = clothes, coats, shoes. "
                    "personal_care = showers, laundry, haircuts, hygiene. "
                    "medical = doctors, clinics, dental, vision. "
                    "mental_health = counseling, therapy, substance abuse, support groups. "
                    "legal = lawyers, immigration, eviction, legal aid. "
                    "employment = jobs, resume help, training. "
                    "other = benefits, SNAP, IDs, birth certificates, free phones."
                ),
            },
            "location": {
                "type": "string",
                "description": (
                    "The NYC borough or neighborhood where the user wants services. "
                    "Extract ONLY the location name — never include surrounding words. "
                    "For example, 'in East New York but they can't keep me' → 'East New York'. "
                    "Extract the INTENDED location, not where they currently are if different. "
                    "For example, 'I'm in Queens but need food in Brooklyn' → 'Brooklyn'. "
                    "Use the neighborhood or borough name as stated by the user."
                ),
            },
            "age": {
                "type": "integer",
                "description": (
                    "The age of the person who needs services. "
                    "May be the user or someone they're asking about "
                    "(e.g., 'my son is 12' → 12). "
                    "Must be between 1 and 119."
                ),
            },
            "urgency": {
                "type": "string",
                "enum": ["high", "medium"],
                "description": (
                    "high = tonight, right now, urgent, emergency, ASAP. "
                    "medium = soon, this week. "
                    "Omit if no urgency indicated."
                ),
            },
            "gender": {
                "type": "string",
                "description": (
                    "The gender of the person who needs services, if mentioned. "
                    "Used for gendered shelters and services."
                ),
            },
        },
        "required": [],
    },
}

_SYSTEM_PROMPT = (
    "You are a slot extraction engine for a social services chatbot in NYC. "
    "Extract structured information from the user's message using the "
    "extract_intake_slots tool. Only extract what is explicitly stated or "
    "strongly implied. Do not guess or assume. If the message doesn't contain "
    "any service-related information, call the tool with an empty object {}."
)


# ---------------------------------------------------------------------------
# LLM EXTRACTION
# ---------------------------------------------------------------------------

def extract_slots_llm(message: str) -> dict:
    """
    Use Claude function calling to extract slots from a message.

    Returns a dict with keys: service_type, location, age, urgency, gender.
    Values are None for slots that couldn't be extracted.
    """
    try:
        client = _get_client()

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACT_SLOTS_TOOL],
            tool_choice={"type": "tool", "name": "extract_intake_slots"},
            messages=[{"role": "user", "content": message}],
        )

        # Extract the tool call result
        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_intake_slots":
                raw = block.input
                return {
                    "service_type": raw.get("service_type"),
                    "location": raw.get("location"),
                    "age": raw.get("age"),
                    "urgency": raw.get("urgency"),
                    "gender": raw.get("gender"),
                }

        logger.warning("Claude did not return a tool call")
        return _empty_slots()

    except Exception as e:
        logger.error(f"LLM slot extraction failed: {e}")
        return _empty_slots()


def _empty_slots() -> dict:
    return {
        "service_type": None,
        "location": None,
        "age": None,
        "urgency": None,
        "gender": None,
    }


# ---------------------------------------------------------------------------
# COMPLEXITY CHECK
# ---------------------------------------------------------------------------

def _is_simple_message(message: str, regex_result: dict) -> bool:
    """
    Determine if a message is simple enough to trust regex extraction.

    Simple = short, clear keyword match, known location, no ambiguity.
    Complex = long sentences, implicit needs, conflicting signals, slang.

    When in doubt, return False (use LLM) — accuracy > speed.
    """
    words = message.split()

    # Long messages are always complex
    if len(words) > 8:
        return False

    has_service = regex_result.get("service_type") is not None
    has_location = regex_result.get("location") is not None

    # If regex didn't get both, it's not simple
    if not (has_service and has_location):
        return False

    # Check if the extracted location is a known NYC location
    # (not a greedy-captured sentence fragment)
    from app.services.slot_extractor import _KNOWN_LOCATIONS, NEAR_ME_SENTINEL
    location = regex_result.get("location", "")
    if location == NEAR_ME_SENTINEL:
        return True  # "near me" is simple
    location_is_known = any(
        loc == location.lower().strip()
        for loc in _KNOWN_LOCATIONS
    )
    if not location_is_known:
        return False  # Unknown location may be garbled — let LLM handle

    # Check for multiple service-type keywords (conflicting signals)
    from app.services.slot_extractor import SERVICE_KEYWORDS
    lower = message.lower()
    matched_categories = set()
    for cat, keywords in SERVICE_KEYWORDS.items():
        for kw in keywords:
            if len(kw) > 3 and kw in lower:  # only check non-short keywords
                matched_categories.add(cat)
    if len(matched_categories) > 1:
        return False  # Conflicting service signals — let LLM disambiguate

    return True


# ---------------------------------------------------------------------------
# SMART EXTRACTOR — complexity-based routing
# ---------------------------------------------------------------------------

def extract_slots_smart(message: str) -> dict:
    """
    Extract slots using complexity-based routing:

    1. Regex runs first (fast, free)
    2. If message is SIMPLE and regex got clear results → use regex
    3. If message is COMPLEX → call LLM (authoritative, no merge)
    4. If LLM fails → fall back to regex

    Returns the same dict shape as extract_slots().
    """
    from app.services.slot_extractor import extract_slots as extract_slots_regex

    # Step 1: Regex extraction (always runs — fast)
    regex_result = extract_slots_regex(message)

    # Step 2: Complexity check
    if _is_simple_message(message, regex_result):
        logger.debug("Simple message — using regex results")
        return regex_result

    # Step 3: Complex message — LLM is authoritative
    logger.info("Complex message — calling LLM for slot extraction")
    llm_result = extract_slots_llm(message)

    # If LLM returned something useful, use it
    llm_has_data = any(v is not None for v in llm_result.values())
    if llm_has_data:
        # Supplement with regex for any slots LLM missed
        # (e.g., LLM got service+location but missed urgency)
        for key in regex_result:
            if llm_result.get(key) is None and regex_result.get(key) is not None:
                llm_result[key] = regex_result[key]
        return llm_result

    # Step 4: LLM returned nothing — fall back to regex
    logger.warning("LLM returned empty — falling back to regex")
    return regex_result
