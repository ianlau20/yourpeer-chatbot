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

Multi-service support (PR 4):
    - "I need food and a place to crash" → service_type=food,
      additional_service_types=["shelter"]
    - The LLM detects indirect phrasing that regex misses (e.g.,
      "a place to crash" → shelter, "someone to talk to" → mental_health)
    - extract_slots_smart() merges LLM additional services with regex
      additional_services, deduplicating by category.
"""

import os
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Use the shared Anthropic client and model constants
from app.llm.claude_client import get_client, SLOT_EXTRACTION_MODEL


# ---------------------------------------------------------------------------
# SERVICE TYPE ENUM (shared between tool schema and validation)
# ---------------------------------------------------------------------------

_SERVICE_TYPE_ENUM = [
    "food", "shelter", "clothing", "personal_care",
    "medical", "mental_health", "legal", "employment", "other",
]


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
                "enum": _SERVICE_TYPE_ENUM,
                "description": (
                    "The primary type of service the user is looking for. "
                    "If the user mentions multiple needs, put the most urgent "
                    "or first-mentioned here. "
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
            "additional_service_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": _SERVICE_TYPE_ENUM,
                },
                "description": (
                    "Any additional service types the user needs beyond the "
                    "primary one. For example, if the user says 'I need food "
                    "and a place to crash,' service_type is 'food' and "
                    "additional_service_types is ['shelter']. Only include "
                    "services the user explicitly or clearly implicitly "
                    "requests. Do not infer services that weren't mentioned. "
                    "Do not repeat the primary service_type here."
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
                    "Must be between 1 and 110."
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
            "family_status": {
                "type": "string",
                "enum": ["with_children", "with_family", "alone"],
                "description": (
                    "with_children = user has children, kids, a baby, or is pregnant. "
                    "with_family = user is with a partner, spouse, or other family. "
                    "alone = user explicitly says they are alone or by themselves. "
                    "Omit if not mentioned."
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
    "any service-related information, call the tool with an empty object {}.\n\n"
    "If the user mentions multiple service needs, put the most urgent or "
    "first-mentioned in service_type and any others in additional_service_types. "
    "For example: 'I need food and somewhere to sleep' → service_type: 'food', "
    "additional_service_types: ['shelter']. Do not repeat the primary service in "
    "additional_service_types.\n\n"
    "You may receive prior conversation turns for context. Use them to resolve "
    "references like 'there', 'that area', 'try Queens instead', or 'what about "
    "Brooklyn?' — but only extract slots from the LATEST user message."
)


# ---------------------------------------------------------------------------
# LLM EXTRACTION
# ---------------------------------------------------------------------------

def extract_slots_llm(message: str, conversation_history: list = None) -> dict:
    """
    Use Claude function calling to extract slots from a message.

    Args:
        message: The current user message to extract slots from.
        conversation_history: Optional list of prior turns, each a dict
            with keys 'role' ('user' or 'assistant') and 'text'.
            Provides context for follow-up messages like
            "What about in Brooklyn?" or "Try Queens instead".

    Returns a dict with keys: service_type, additional_service_types,
    location, age, urgency, gender, family_status.
    Values are None for slots that couldn't be extracted;
    additional_service_types defaults to [].
    """
    try:
        client = get_client()

        # Build messages with conversation history for context
        messages = []
        if conversation_history:
            # Include up to the last 6 turns (3 user + 3 bot) to stay
            # within a reasonable token budget for slot extraction.
            recent = conversation_history[-6:]
            for turn in recent:
                role = turn.get("role", "user")
                text = turn.get("text", "")
                api_role = "user" if role == "user" else "assistant"

                # Claude API requires strictly alternating roles.
                # If we'd have two consecutive same-role messages,
                # insert a placeholder for the other role.
                if messages and messages[-1]["role"] == api_role:
                    placeholder_role = "assistant" if api_role == "user" else "user"
                    messages.append({"role": placeholder_role, "content": "(continuing)"})

                messages.append({"role": api_role, "content": text})

            # Ensure the last history message isn't "user" — we're about
            # to append the current user message.
            if messages and messages[-1]["role"] == "user":
                messages.append({"role": "assistant", "content": "(listening)"})

        # Add the current message
        messages.append({"role": "user", "content": message})

        response = client.messages.create(
            model=SLOT_EXTRACTION_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACT_SLOTS_TOOL],
            tool_choice={"type": "tool", "name": "extract_intake_slots"},
            messages=messages,
        )

        # Extract the tool call result
        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_intake_slots":
                raw = block.input
                return {
                    "service_type": raw.get("service_type"),
                    "additional_service_types": raw.get("additional_service_types") or [],
                    "location": raw.get("location"),
                    "age": raw.get("age"),
                    "urgency": raw.get("urgency"),
                    "gender": raw.get("gender"),
                    "family_status": raw.get("family_status"),
                }

        logger.warning("Claude did not return a tool call")
        return _empty_slots()

    except Exception as e:
        logger.error(f"LLM slot extraction failed: {e}")
        return _empty_slots()


def _empty_slots() -> dict:
    return {
        "service_type": None,
        "additional_service_types": [],
        "location": None,
        "age": None,
        "urgency": None,
        "gender": None,
        "family_status": None,
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

def extract_slots_smart(message: str, conversation_history: list = None) -> dict:
    """
    Extract slots using complexity-based routing:

    1. Regex runs first (fast, free)
    2. If message is SIMPLE and regex got clear results → use regex
    3. If message is COMPLEX → call LLM with conversation history
       (authoritative, no merge)
    4. If LLM fails → fall back to regex

    Multi-service merge (PR 4):
        After determining the primary result, additional services from
        both regex and LLM are merged. Regex additional_services take
        precedence (they have detail info like "food stamps"). LLM adds
        services that regex missed (e.g., "a place to crash" → shelter).
        The primary service_type is excluded from additional_services.

    Args:
        message: The current user message.
        conversation_history: Optional list of prior turns for LLM context.
            Each item is a dict with 'role' and 'text' keys.

    Returns the same dict shape as extract_slots(), with additional_services
    merged from both regex and LLM sources.
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
    llm_result = extract_slots_llm(message, conversation_history=conversation_history)

    # If LLM returned something useful, use it as the base
    llm_has_data = any(
        v is not None and v != []
        for v in llm_result.values()
    )
    if llm_has_data:
        # Supplement with regex for any slots LLM missed
        # (e.g., LLM got service+location but missed urgency)
        for key in regex_result:
            # Skip additional_services — handled separately below
            if key == "additional_services":
                continue
            if llm_result.get(key) is None and regex_result.get(key) is not None:
                llm_result[key] = regex_result[key]

        # Prefer regex service_type over LLM when regex found an explicit
        # keyword match. The regex match is deterministic ("dental" is
        # literally in the text) while the LLM can be biased by conversation
        # history — e.g., returning "personal_care" for "What about dental
        # care?" because the prior turns were about showers.
        if (regex_result.get("service_type") is not None
                and llm_result.get("service_type") != regex_result["service_type"]):
            logger.info(
                f"Regex service_type override: llm='{llm_result.get('service_type')}' "
                f"→ regex='{regex_result['service_type']}' "
                f"(explicit keyword match in message)"
            )
            llm_result["service_type"] = regex_result["service_type"]

        merged = llm_result
    else:
        # Step 4: LLM returned nothing — fall back to regex.
        # regex_result already has correct additional_services — return as-is.
        logger.warning("LLM returned empty — falling back to regex")
        return regex_result

    # -----------------------------------------------------------------
    # Merge additional services from regex and LLM (PR 4)
    # -----------------------------------------------------------------
    # Regex additional_services: list of (service_type, detail) tuples
    regex_additional = regex_result.get("additional_services", [])

    # LLM additional_service_types: list of service_type strings
    llm_additional = merged.pop("additional_service_types", []) or []

    # Build combined list, deduplicating by service category.
    # Primary service_type is excluded (no duplication with main slot).
    seen = set()
    primary = merged.get("service_type")
    if primary:
        seen.add(primary)

    combined_additional = []

    # Regex additional first — they have detail info (e.g., "food stamps")
    for svc, detail in regex_additional:
        if svc not in seen:
            combined_additional.append((svc, detail))
            seen.add(svc)

    # LLM additional — only services regex didn't already find.
    # This is where the LLM adds value: indirect phrasing like
    # "a place to crash" → shelter, "someone to talk to" → mental_health
    for svc in llm_additional:
        if svc not in seen:
            combined_additional.append((svc, None))
            seen.add(svc)
            logger.info(
                f"LLM detected additional service '{svc}' "
                f"that regex missed"
            )

    if combined_additional:
        merged["additional_services"] = combined_additional

    return merged
