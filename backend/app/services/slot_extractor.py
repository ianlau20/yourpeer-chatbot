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
        "pantry", "hungry", "soup kitchen", "soup", "lunch", "dinner",
        "breakfast", "snack", "free food", "hot meal", "brown bag",
        "farmers market", "mobile pantry",
        "something to eat", "grab a bite", "canned food",
        # NYC-specific (P3 audit)
        "baby formula", "formula", "wic", "diapers",
    ],

    # --- Shelter & Housing (taxonomy: Shelter) ---
    "shelter": [
        "shelter", "place to stay", "housing", "sleep tonight",
        "place to sleep", "somewhere to sleep", "homeless", "unhoused",
        "drop-in center", "drop in center", "warming center",
        "overnight", "transitional housing", "safe haven", "room",
        "place to live", "somewhere to live", "intake",
        "evicted", "kicked out", "kicked me out", "on the street",
        "sleeping outside", "somewhere safe", "safe place",
        # NYC-specific (P3 audit)
        "path center", "dhs intake", "domestic violence shelter",
    ],

    # --- Clothing (taxonomy: Clothing) ---
    "clothing": [
        "clothing", "clothes", "jacket", "coat", "shoes", "boots",
        "socks", "underwear", "warm clothes", "winter clothes",
        "free clothes", "outfit", "pants", "shirt",
        "sweater", "sweatshirt", "hoodie", "gloves",
        "winter gear", "sneakers",
    ],

    # --- Personal Care (taxonomy: Personal Care → Shower, Laundry, etc.) ---
    "personal_care": [
        "shower", "showers", "hygiene", "clean up", "laundry",
        "toiletries", "restroom", "bathroom", "haircut", "barber",
        "toothbrush", "toothpaste", "soap", "shampoo", "deodorant",
        "personal care", "grooming",
        "hygiene kit", "feminine products", "pads", "tampons",
        "menstrual", "razors", "freshen up", "get clean",
    ],

    # --- Health Care (taxonomy: Health) ---
    "medical": [
        "doctor", "clinic", "medical", "hospital", "medicine", "health",
        "health care", "healthcare", "prescription", "dental", "dentist",
        "eye doctor", "vision", "glasses", "urgent care", "checkup",
        "physical", "vaccination", "vaccine", "std testing", "hiv testing",
        "sick", "nurse", "wound", "injury", "infection",
        "medication", "blood pressure", "sti testing",
        # Harm reduction / community health (P3 audit)
        "methadone", "suboxone", "narcan", "naloxone",
        "walk-in clinic", "walk in clinic",
    ],

    # --- Mental Health (taxonomy: Mental Health) ---
    "mental_health": [
        "mental health", "counseling", "counselor", "therapist", "therapy",
        "depression", "anxiety", "trauma", "ptsd",
        "substance abuse", "addiction", "rehab", "recovery",
        "aa meeting", "na meeting", "narcotics anonymous", "alcoholics anonymous",
        "support group", "emotional support", "psychiatric",
        "psychiatrist", "crisis counseling",
        "grief", "grieving",
        # NOTE: "struggling", "having a hard time", "someone to talk to",
        # and "peer support" removed — they are emotional expressions or
        # escalation signals, not mental health service requests. Keeping
        # them here caused "I'm struggling and need shelter" to misclassify.
    ],

    # --- Legal Services (taxonomy: Legal Services, Advocates / Legal Aid) ---
    "legal": [
        "legal", "lawyer", "attorney", "court", "eviction", "immigration",
        "legal aid", "legal help", "legal services", "tenant rights",
        "asylum", "deportation", "green card", "visa", "work permit",
        "public defender", "advocate", "rights",
        "landlord", "tenant", "custody", "bail",
        "housing court", "discrimination",
    ],

    # --- Employment (taxonomy: Employment) ---
    "employment": [
        "job", "jobs", "employment", "hiring", "career",
        "resume", "interview", "job training", "vocational",
        "workforce", "job placement", "temp work", "day labor",
        "job search", "job help", "find work", "need work",
        "looking for work",
        "apprenticeship", "part-time", "gig work",
    ],

    # --- Other Services (taxonomy: Other service) ---
    "other": [
        "other services", "other service",
        "benefits", "snap", "ebt", "food stamps", "medicaid",
        "social security", "disability", "ssi", "public assistance",
        "identification", "birth certificate", "need an id",
        "free phone", "wifi", "internet", "charging", "mail",
        "mailing address", "storage", "locker",
        "welfare", "cash assistance", "state id", "nyc id",
        "metro card", "transit", "charger", "charging station",
        # NYC-specific (P3 audit)
        "voter registration", "replacement id",
        "tax prep", "tax preparation", "free tax",
    ],
}

# Keywords that were previously removed due to substring collisions with
# location names or common phrases. These are matched using \b word
# boundaries instead of plain `in` to prevent false positives.
# Format: { keyword: service_type }
_WORD_BOUNDARY_KEYWORDS = {
    "bed": "shelter",          # was colliding with "bed-stuy", "bedford"
    "wash": "personal_care",   # was colliding with "washington heights"
    # NOTE: "work" not included here — "\bwork\b" still matches "how does
    # this work". Use the phrase-based keywords ("need work", "find work",
    # "looking for work") in SERVICE_KEYWORDS instead.
    "id": "other",             # was colliding with "side", "ridge", "midtown"
    "eat": "food",             # was colliding with "beat", "seat", "theater"
    "hat": "clothing",         # was colliding with "what", "that", "chat"
    "stress": "mental_health", # was colliding with "stressed out", "so stressed"
                               # (emotional expressions, not service requests)
}

# Pre-compile word-boundary patterns for collision-prone keywords
_WORD_BOUNDARY_PATTERNS = {
    kw: (re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE), svc)
    for kw, svc in _WORD_BOUNDARY_KEYWORDS.items()
}

# Phrases that mean "where I am" but don't contain an actual location.
# When detected, we store a sentinel so the follow-up logic knows to ask
# for a real neighborhood/borough instead of running a broken query.
_NEAR_ME_PHRASES = [
    "near me",
    "close to me",
    "around me",
    "close to",
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

# Notable sub-types — specific keywords whose user-facing label differs
# from the parent category label. When one of these matches, the
# confirmation message echoes the user's specific term instead of the
# generic category name. Only includes keywords where the generic label
# would confuse the user (e.g., "dental" → "health care" loses context).
_NOTABLE_SUB_TYPES = {
    # medical sub-types
    "dental": "dental care",
    "dentist": "dental care",
    "eye doctor": "vision care",
    "vision": "vision care",
    "glasses": "vision care",
    "urgent care": "urgent care",
    "std testing": "STD testing",
    "sti testing": "STI testing",
    "hiv testing": "HIV testing",
    "vaccination": "vaccinations",
    "vaccine": "vaccinations",
    # mental_health sub-types
    "substance abuse": "substance abuse services",
    "addiction": "addiction services",
    "rehab": "rehab services",
    "recovery": "recovery services",
    "aa meeting": "AA meetings",
    "na meeting": "NA meetings",
    "counseling": "counseling",
    "therapy": "therapy",
    # legal sub-types
    "immigration": "immigration services",
    "eviction": "eviction help",
    "asylum": "asylum services",
    # personal_care sub-types
    "shower": "showers",
    "laundry": "laundry",
    "haircut": "haircuts",
    # food sub-types
    "soup kitchen": "soup kitchens",
    "food pantry": "food pantries",
    "groceries": "groceries",
}

def _extract_all_service_types(text: str) -> list[tuple[str, Optional[str]]]:
    """Extract ALL service type categories from a message.

    Returns a list of (service_type, service_detail) tuples, deduplicated
    by category. Order reflects first appearance in text.

    Examples:
        "I need food and shelter" → [("food", None), ("shelter", None)]
        "dental care in Brooklyn" → [("medical", "dental care")]
        "hello" → []
    """
    lower = text.lower()
    # Each entry: (text_position, service_type, service_detail)
    found = []
    seen_categories = set()
    matched_spans = []  # track matched positions to avoid sub-matches

    # Build a flat list of (keyword, service_type) sorted longest-first.
    # This ensures "mental health" matches before "health",
    # "food bank" before "food", etc.
    all_keywords = []
    for service, keywords in SERVICE_KEYWORDS.items():
        for kw in keywords:
            all_keywords.append((kw, service))
    all_keywords.sort(key=lambda x: len(x[0]), reverse=True)

    for keyword, service in all_keywords:
        # Scan for ALL occurrences of this keyword, not just the first.
        # This fixes the bug where find() returns a position inside an
        # already-matched longer keyword, causing later occurrences to
        # be missed (e.g., "food stamps and food" — first "food" at pos 7
        # is inside "food stamps", but "food" at pos 23 is independent).
        search_start = 0
        while True:
            pos = lower.find(keyword, search_start)
            if pos == -1:
                break

            end = pos + len(keyword)

            # Skip if this position overlaps with an already-matched span
            if any(pos < ms_end and end > ms_start
                   for ms_start, ms_end in matched_spans):
                search_start = pos + 1
                continue

            # Record the span (even for already-seen categories, to block
            # sub-matches at this position)
            matched_spans.append((pos, end))

            if service not in seen_categories:
                detail = _NOTABLE_SUB_TYPES.get(keyword)
                found.append((pos, service, detail))
                seen_categories.add(service)

            # Move past this match
            search_start = end
            break  # found a valid (non-overlapping) position for this keyword

    # Fallback: check collision-prone keywords using word boundaries
    for kw, (pattern, service) in _WORD_BOUNDARY_PATTERNS.items():
        if service not in seen_categories:
            m = pattern.search(text)
            if m:
                detail = _NOTABLE_SUB_TYPES.get(kw)
                found.append((m.start(), service, detail))
                seen_categories.add(service)

    # Sort by text position so the primary service is what the user
    # mentioned first, not whichever keyword happens to be longest.
    found.sort(key=lambda x: x[0])

    return [(svc, detail) for _, svc, detail in found]


def _extract_service_type(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extract the primary service type category from a message.

    Returns (service_type, service_detail) for the first match.
    For all matches, use _extract_all_service_types().
    """
    all_types = _extract_all_service_types(text)
    if all_types:
        return all_types[0]
    return None, None


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

    # Preposition + known location: "in Brooklyn", "near Queens",
    # "around Harlem", "by Midtown", "from the Bronx"
    # First, try to match a preposition followed by a KNOWN location.
    # This prevents the greedy capture bug where "in East New York but
    # they can't keep me anymore" grabs way past the location name.
    for loc in _KNOWN_LOCATIONS:
        pattern = r"\b(?:in|near|around|by|from|over in|out in)\s+" + re.escape(loc) + r"\b"
        if re.search(pattern, lower):
            return loc

    # Fallback: preposition + short capture (max 25 chars, stop at common
    # stop words to prevent grabbing sentence fragments)
    prep_match = re.search(
        r"\b(?:in|near|around|by|from|over in|out in)\s+"
        r"([a-zA-Z][a-zA-Z\s\-]{1,24}?)"
        r"(?:\s+(?:but|and|or|that|who|where|when|for|to|i|my|the|they|we|it|is|are|was|can|do)\b|[,.\?!]|$)",
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
# Sorted longest-first so "east new york" matches before "new york",
# "long island city" before "island", etc.
_KNOWN_LOCATIONS = [
    # Multi-word (longest first)
    "long island city", "jackson heights", "washington heights",
    "financial district", "bedford-stuyvesant", "prospect heights",
    "lower east side", "upper west side", "upper east side",
    "east new york", "east village", "west village", "east harlem",
    "midtown east", "midtown west", "times square",
    "port authority", "penn station", "grand central",
    "crown heights", "cobble hill", "sunset park",
    "bay ridge", "far rockaway", "fort greene",
    "park slope", "red hook", "south bronx", "mott haven",
    "hunts point", "little italy", "battery park",
    "hells kitchen", "hell's kitchen", "kips bay",
    "murray hill", "staten island", "the bronx",
    # Single/short words
    "manhattan", "brooklyn", "queens", "bronx",
    "harlem", "midtown", "soho", "tribeca", "chelsea",
    "williamsburg", "bushwick", "bed-stuy", "flatbush",
    "brownsville", "inwood", "gramercy", "chinatown",
    "nolita", "noho", "dumbo",
    "astoria", "flushing", "jamaica", "ridgewood",
    "woodside", "sunnyside", "corona", "elmhurst",
    "fordham", "morrisania",
]


def _extract_urgency(text: str) -> Optional[str]:
    lower = text.lower()
    if any(x in lower for x in [
        "tonight", "urgent", "asap", "right now", "immediately",
        "emergency", "today", "before dark", "freezing",
    ]):
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


def _extract_family_status(text: str) -> Optional[str]:
    """Extract family composition from user message.

    Returns one of: 'with_children', 'with_family', 'alone', or None.
    Only extracts when clearly stated — avoids guessing.

    Check order matters: children > family > alone.
    "single mother" must match children before "single" matches alone.
    """
    lower = text.lower()

    # With children — most specific, check first
    child_phrases = [
        "with my kid", "with my kids", "with my child", "with my children",
        "have kids", "have children", "have a kid", "have a child",
        "my son", "my daughter", "my baby", "my toddler", "my infant",
        "two kids", "three kids", "four kids",
        "2 kids", "3 kids", "4 kids",
        "with a baby", "with a toddler", "with an infant",
        "my kids are", "my children are",
        "year old daughter", "year old son", "year old child",
        "pregnant",
        # "single parent/mother/father" = has children, not alone
        "single mother", "single mom", "single father", "single dad",
        "single parent",
    ]
    for phrase in child_phrases:
        if phrase in lower:
            return "with_children"

    # With family — broader family unit
    # NOTE: "me and my" removed — too broad ("me and my friend" is not family)
    family_phrases = [
        "with my family", "with my partner", "with my wife",
        "with my husband", "with my spouse",
        "with my girlfriend", "with my boyfriend",
        "me and my wife", "me and my husband", "me and my partner",
    ]
    for phrase in family_phrases:
        if phrase in lower:
            return "with_family"

    # Alone — explicit statements
    # NOTE: "single" alone is ambiguous — only match exact "i'm single"
    # or the word in clear context. "single mother" is caught above.
    alone_phrases = [
        "i'm alone", "im alone", "i am alone",
        "by myself", "on my own", "just me",
        "no family", "no one with me",
        "nobody with me",
    ]
    for phrase in alone_phrases:
        if phrase in lower:
            return "alone"

    return None


def extract_slots(message: str) -> dict:
    all_types = _extract_all_service_types(message)

    service_type = None
    service_detail = None
    additional_services = []

    if all_types:
        service_type, service_detail = all_types[0]
        additional_services = all_types[1:]  # remaining (service, detail) tuples

    return {
        "service_type": service_type,
        "service_detail": service_detail,
        "additional_services": additional_services,
        "location": _extract_location(message),
        "urgency": _extract_urgency(message),
        "age": _extract_age(message),
        "family_status": _extract_family_status(message),
    }


def merge_slots(existing: dict, new_values: dict) -> dict:
    merged = dict(existing)
    for key, value in new_values.items():
        # additional_services is transient extraction metadata —
        # never persist it in session state.
        if key == "additional_services":
            continue
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

    # When service_type changes, clear stale service_detail so the
    # confirmation message doesn't show the old sub-type label.
    if (new_values.get("service_type") is not None
            and new_values["service_type"] != existing.get("service_type")):
        if new_values.get("service_detail") is None:
            merged.pop("service_detail", None)

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

    if slots.get("service_type") == "shelter" and not slots.get("family_status"):
        return "Are you on your own, or do you have family or children with you?"

    return "Could you share one more detail to help me narrow options?"
