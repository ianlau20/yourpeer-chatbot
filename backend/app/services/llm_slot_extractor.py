"""
LLM-Based Slot Extractor

Uses Claude function calling to extract structured intake slots from
natural language. Falls back to the regex extractor for simple inputs
where the LLM adds no value (saving API calls and latency).

Strategy:
    1. Run regex extraction first (fast, free, handles 80% of inputs)
    2. If regex found a service_type AND location → use regex results (done)
    3. If regex found partial or nothing → call Claude to extract slots
    4. Merge LLM results with regex results (LLM wins on conflicts)

This keeps API costs low while handling nuanced inputs like:
    - "I'm in Queens but looking for food in the Bronx"
    - "my son is 12 and needs a coat"
    - "somewhere safe for tonight, I'm a woman"
    - "I was just released from Rikers"
"""

import os
import json
import logging
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
                    "shelter = housing, place to sleep, drop-in centers. "
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
# SMART EXTRACTOR — regex first, LLM when needed
# ---------------------------------------------------------------------------

def extract_slots_smart(message: str) -> dict:
    """
    Extract slots using a tiered approach:
    1. Regex first (fast, free)
    2. LLM only if regex didn't get enough

    Returns the same dict shape as extract_slots().
    """
    from app.services.slot_extractor import extract_slots as extract_slots_regex

    # Step 1: Regex extraction (always runs)
    regex_result = extract_slots_regex(message)

    has_service = regex_result.get("service_type") is not None
    has_location = regex_result.get("location") is not None

    # Step 2: If regex got both service + location, we're done
    if has_service and has_location:
        logger.debug("Regex extracted enough — skipping LLM")
        return regex_result

    # Step 3: Call LLM for complex/ambiguous inputs
    logger.info("Regex insufficient — calling LLM for slot extraction")
    llm_result = extract_slots_llm(message)

    # Step 4: Merge — LLM wins on conflicts, regex fills gaps
    merged = {}
    all_keys = set(list(regex_result.keys()) + list(llm_result.keys()))
    for key in all_keys:
        llm_val = llm_result.get(key)
        regex_val = regex_result.get(key)
        # LLM result takes priority if it has a value
        if llm_val is not None:
            merged[key] = llm_val
        elif regex_val is not None:
            merged[key] = regex_val
        else:
            merged[key] = None

    return merged
