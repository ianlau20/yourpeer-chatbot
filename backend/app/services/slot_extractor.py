import re
from typing import Optional

# NOTE: This file contains a simple rule-based slot extractor used for early
# prototyping. It relies on keyword matching and basic regex patterns, so it
# may fail on nuanced or multi-part requests where context matters
# (e.g., "I'm in Queens but looking for a food bank in the Bronx").
# Future versions may replace or augment this logic with LLM-based slot filling
# for more flexible and accurate interpretation.

SERVICE_KEYWORDS = {
    # --- Food (taxonomy: Food, Food Pantry, Mobile Pantry, etc.) ---
    "food": [
        "food", "food bank", "food pantry", "meal", "meals", "groceries",
        "pantry", "eat", "hungry", "soup kitchen", "soup", "lunch", "dinner",
        "breakfast", "snack", "free food", "hot meal", "brown bag",
        "farmers market", "mobile pantry",
    ],

    # --- Shelter & Housing (taxonomy: Shelter) ---
    "shelter": [
        "shelter", "place to stay", "bed", "housing", "sleep tonight",
        "place to sleep", "somewhere to sleep", "homeless", "unhoused",
        "drop-in center", "drop in center", "warming center",
        "overnight", "transitional housing", "safe haven", "room",
        "place to live", "somewhere to live", "intake",
    ],

    # --- Clothing (taxonomy: Clothing) ---
    "clothing": [
        "clothing", "clothes", "jacket", "coat", "shoes", "boots",
        "socks", "underwear", "warm clothes", "winter clothes",
        "free clothes", "outfit", "pants", "shirt",
    ],

    # --- Personal Care (taxonomy: Personal Care → Shower, Laundry, etc.) ---
    "personal_care": [
        "shower", "showers", "hygiene", "wash", "clean up", "laundry",
        "toiletries", "restroom", "bathroom", "haircut", "barber",
        "toothbrush", "toothpaste", "soap", "shampoo", "deodorant",
        "personal care", "grooming",
    ],

    # --- Health Care (taxonomy: Health) ---
    "medical": [
        "doctor", "clinic", "medical", "hospital", "medicine", "health",
        "health care", "healthcare", "prescription", "dental", "dentist",
        "eye doctor", "vision", "glasses", "urgent care", "checkup",
        "physical", "vaccination", "vaccine", "std", "hiv", "testing",
    ],

    # --- Mental Health (taxonomy: Mental Health) ---
    "mental_health": [
        "mental health", "counseling", "counselor", "therapist", "therapy",
        "depression", "anxiety", "stress", "trauma", "ptsd",
        "substance abuse", "addiction", "rehab", "recovery", "aa",
        "na", "support group", "emotional support", "psychiatric",
        "psychiatrist", "crisis counseling",
    ],

    # --- Legal Services (taxonomy: Legal Services, Advocates / Legal Aid) ---
    "legal": [
        "legal", "lawyer", "attorney", "court", "eviction", "immigration",
        "legal aid", "legal help", "legal services", "tenant rights",
        "asylum", "deportation", "green card", "visa", "work permit",
        "public defender", "advocate", "rights",
    ],

    # --- Employment (taxonomy: Employment) ---
    "employment": [
        "job", "jobs", "work", "employment", "hiring", "career",
        "resume", "interview", "job training", "vocational",
        "workforce", "job placement", "temp work", "day labor",
        "job search", "job help",
    ],

    # --- Other Services (taxonomy: Other service) ---
    "other": [
        "benefits", "snap", "ebt", "food stamps", "medicaid",
        "social security", "disability", "ssi", "public assistance",
        "id", "identification", "birth certificate", "phone",
        "free phone", "wifi", "internet", "charging", "mail",
        "mailing address", "storage", "locker",
    ],
}

# Phrases that mean "where I am" but don't contain an actual location.
# When detected, we store a sentinel so the follow-up logic knows to ask
# for a real neighborhood/borough instead of running a broken query.
_NEAR_ME_PHRASES = [
    "near me",
    "close to me",
    "around me",
    "close by",
    "nearby",
    "closest",
    "around here",
    "in my area",
    "where i am",
]

# Sentinel value stored when user says "near me" without a real location.
NEAR_ME_SENTINEL = "__near_me__"


# TODO: Current implementation assumes a single service intent.
# This will fail for multi-intent queries (e.g., "food and housing").
# Consider returning a list of services instead of a single value.
def _extract_service_type(text: str) -> Optional[str]:
    lower = text.lower()

    # Build a flat list of (keyword, service_type) sorted longest-first.
    # This ensures "mental health" matches before "health",
    # "food bank" before "food", "substance abuse" before "abuse", etc.
    all_keywords = []
    for service, keywords in SERVICE_KEYWORDS.items():
        for kw in keywords:
            all_keywords.append((kw, service))
    all_keywords.sort(key=lambda x: len(x[0]), reverse=True)

    for keyword, service in all_keywords:
        if keyword in lower:
            return service
    return None


def _extract_location(text: str) -> Optional[str]:
    lower = text.lower()

    # Check for "near me" phrases first — these are NOT real locations.
    # Important: check these BEFORE the preposition patterns so that
    # "near me" doesn't fall through to the "near <location>" pattern.
    for phrase in _NEAR_ME_PHRASES:
        if phrase in lower:
            # But only if there's no known location after the "near me" phrase.
            # "Food near me in Brooklyn" should extract Brooklyn, not sentinel.
            remainder = lower[lower.index(phrase) + len(phrase):]
            has_real_location_after = any(loc in remainder for loc in _KNOWN_LOCATIONS)
            if not has_real_location_after:
                return NEAR_ME_SENTINEL

    # Preposition + location pattern: "in Brooklyn", "near Queens",
    # "around Harlem", "by Midtown", "from the Bronx"
    prep_match = re.search(
        r"\b(?:in|near|around|by|from|over in|out in)\s+([a-zA-Z][a-zA-Z\s\-]{1,40})",
        text,
        re.IGNORECASE,
    )
    if prep_match:
        candidate = prep_match.group(1).strip()
        candidate_lower = candidate.lower()
        # Filter out non-location phrases
        non_locations = [
            "need", "trouble", "danger", "a", "the", "my", "your",
            "here", "there", "me", "help", "this",
        ]
        if candidate_lower.split()[0] not in non_locations:
            return candidate

    # Known NYC boroughs and neighborhoods (bare mention without preposition)
    for loc in _KNOWN_LOCATIONS:
        if loc in lower:
            return loc

    return None


# Known NYC locations — used for both bare-mention extraction and
# the "near me" override check above.
_KNOWN_LOCATIONS = [
    "long island city", "midtown", "soho", "queens", "brooklyn",
    "bronx", "the bronx", "manhattan", "staten island", "harlem",
    "east village", "west village", "chelsea", "williamsburg",
    "bushwick", "bed-stuy", "crown heights", "flatbush",
    "astoria", "flushing", "jamaica", "jackson heights",
    "south bronx", "mott haven", "fordham", "washington heights",
    "east new york", "sunset park", "bay ridge", "far rockaway",
    "lower east side", "upper west side", "upper east side",
    "brownsville", "tribeca", "inwood",
]


def _extract_urgency(text: str) -> Optional[str]:
    lower = text.lower()
    if any(x in lower for x in ["tonight", "urgent", "asap", "right now", "immediately"]):
        return "high"
    if any(x in lower for x in ["soon", "this week"]):
        return "medium"
    return None


def _extract_age(text: str) -> Optional[int]:
    # e.g. "I am 17", "age 22", "22 years old", "I'm 22"
    patterns = [
        r"\bi[' ]?m (\d{1,3})\b",
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
            # If user provides a real location, replace a previous "near me"
            if key == "location" and value != NEAR_ME_SENTINEL:
                merged[key] = value
            elif key == "location" and value == NEAR_ME_SENTINEL:
                # Only store the sentinel if we don't already have a real location
                if not merged.get("location") or merged["location"] == NEAR_ME_SENTINEL:
                    merged[key] = value
            else:
                merged[key] = value
    return merged


def is_enough_to_answer(slots: dict) -> bool:
    # Need service type + a real location (not the "near me" sentinel)
    has_service = bool(slots.get("service_type"))
    has_location = bool(
        slots.get("location")
        and slots["location"] != NEAR_ME_SENTINEL
    )
    return has_service and has_location


def next_follow_up_question(slots: dict) -> str:
    # Ask only ONE targeted question
    if not slots.get("service_type"):
        return "What kind of help do you need right now? I can search for food, shelter, clothing, personal care (showers, laundry, haircuts), health care, mental health, legal help, jobs, or other services like benefits and IDs."

    if not slots.get("location") or slots.get("location") == NEAR_ME_SENTINEL:
        return (
            "I'd love to find services near you! "
            "What neighborhood or borough are you in? "
            "For example: Brooklyn, Queens, Harlem, Midtown."
        )

    if slots.get("service_type") == "shelter" and not slots.get("age"):
        return "To narrow shelter options, can you share your age?"

    return "Could you share one more detail to help me narrow options?"
