import re
from typing import Optional

# NOTE: This file contains a simple rule-based slot extractor used for early
# prototyping. It relies on keyword matching and basic regex patterns, so it
# may fail on nuanced or multi-part requests where context matters
# (e.g., "I'm in Queens but looking for a food bank in the Bronx").
# Future versions may replace or augment this logic with LLM-based slot filling
# for more flexible and accurate interpretation.

SERVICE_KEYWORDS = {
    "food": ["food", "food bank", "meal", "groceries", "pantry"],
    "shelter": ["shelter", "place to stay", "bed", "housing", "sleep tonight"],
    "medical": ["doctor", "clinic", "medical", "hospital", "medicine"],
    "legal": ["legal", "lawyer", "court", "eviction"],
    "employment": ["job", "work", "employment"],
}

# TODO: Current implementation assumes a single service intent.
# This will fail for multi-intent queries (e.g., "food and housing").
# Consider returning a list of services instead of a single value.
def _extract_service_type(text: str) -> Optional[str]:
    lower = text.lower()
    for service, keywords in SERVICE_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return service
    return None


def _extract_location(text: str) -> Optional[str]:
    lower = text.lower()

    # Very simple pattern: "in <location>"
    match = re.search(r"\bin\s+([a-zA-Z][a-zA-Z\s\-]{1,40})", text)
    if match:
        return match.group(1).strip()

    # A few high-value NYC area hints (add more later)
    # NOTE: Hardcoded NYC location hints for now.
    # This should be moved to a separate config/data file and imported here
    # to improve maintainability and scalability.
    known = ["long island city", "midtown", "soho", "queens", "brooklyn", "bronx", "manhattan", "staten island"]
    for loc in known:
        if loc in lower:
            return loc

    return None


def _extract_urgency(text: str) -> Optional[str]:
    lower = text.lower()
    if any(x in lower for x in ["tonight", "urgent", "asap", "right now", "immediately"]):
        return "high"
    if any(x in lower for x in ["soon", "this week"]):
        return "medium"
    return None


def _extract_age(text: str) -> Optional[int]:
    # e.g. "I am 17", "age 22", "22 years old"
    patterns = [
        r"\bi am (\d{1,3})\b",
        r"\bage (\d{1,3})\b",
        r"\b(\d{1,3}) years old\b",
    ]
    for p in patterns:
        m = re.search(p, text.lower())
        if m:
            age = int(m.group(1))
            if 0 < age < 120:
                return age
    return None


def extract_slots(message: str) -> dict:
    return {
        "service_type": _extract_service_type(message),
        "location": _extract_location(message),
        "urgency": _extract_urgency(message),
        "age": _extract_age(message),
    }


def merge_slots(existing: dict, new_values: dict) -> dict:
    merged = dict(existing)
    for key, value in new_values.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


def is_enough_to_answer(slots: dict) -> bool:
    # Keep logic intentionally simple:
    # enough if we know service type + location
    return bool(slots.get("service_type") and slots.get("location"))


def next_follow_up_question(slots: dict) -> str:
    # Ask only ONE targeted question
    if not slots.get("service_type"):
        return "What kind of help do you need right now (food, shelter, medical, legal, or job support)?"
    if not slots.get("location"):
        return "What area or borough are you currently in?"
    if slots.get("service_type") == "shelter" and not slots.get("age"):
        return "To narrow shelter options, can you share your age?"
    return "Could you share one more detail to help me narrow options?"