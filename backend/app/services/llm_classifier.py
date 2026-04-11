"""Unified LLM classification gate for YourPeer chatbot.

When the regex pipeline (slot extraction, action classification, tone
classification) finds nothing on a message of 4+ words, this module makes
a single Haiku call that returns ALL classification dimensions:

    service_type, location, additional_services,
    tone, action, urgency, age, family_status

This replaces two separate LLM calls:
  1. extract_slots_smart() for slot enrichment (Phase 2)
  2. classify_message_llm() for routing fallback

Cost: ~$0.001 per call on Haiku. Only fires when regex fails (~25% of
messages), so monthly cost at 2,000 messages/month is ~$0.50.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VALID CATEGORIES — must stay in sync with chatbot.py routing
# ---------------------------------------------------------------------------

_VALID_SERVICE_TYPES = {
    "food", "shelter", "clothing", "personal_care", "medical",
    "mental_health", "legal", "employment", "other",
}

_VALID_TONES = {
    "emotional", "frustrated", "urgent", "confused", None,
}

_VALID_ACTIONS = {
    "greeting", "thanks", "help", "escalation", "reset",
    "bot_identity", "bot_question",
    "confirm_yes", "confirm_deny",
    "confirm_change_service", "confirm_change_location",
    "correction", "negative_preference",
    None,
}

_VALID_URGENCIES = {"high", "medium", None}

_VALID_FAMILY = {"with_children", "with_family", "alone", None}

# ---------------------------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------------------------

_UNIFIED_SYSTEM_PROMPT = """\
You are a classification engine for YourPeer, an NYC social services chatbot \
for people experiencing homelessness. Given a user message, extract ALL of \
the following and return ONLY a JSON object (no markdown, no explanation):

{
  "service_type": one of: food, shelter, clothing, personal_care, medical, \
mental_health, legal, employment, other, or null if not requesting a service,
  "service_detail": specific sub-type if relevant (e.g. "dental care", \
"food stamps", "detox") or null,
  "location": NYC neighborhood or borough mentioned, lowercase, or null,
  "additional_services": array of {"type": string, "location": string|null} \
for any ADDITIONAL services beyond the primary, or empty array,
  "tone": one of: emotional, frustrated, urgent, confused, or null,
  "action": one of: greeting, thanks, help, escalation, reset, bot_identity, \
bot_question, confirm_yes, confirm_deny, negative_preference, or null,
  "urgency": "high" if tonight/now/emergency, "medium" if soon/this week, \
or null,
  "age": integer if stated, or null,
  "gender": one of: male, female, transgender, nonbinary, lgbtq, or null. \
Only extract if explicitly stated. lgbtq/queer/gay/lesbian = "lgbtq". \
Trans man/FTM = "male". Trans woman/MTF = "female". Non-binary/enby/agender = "nonbinary",
  "family_status": "with_children", "with_family", "alone", or null,
  "populations": array of: "veteran", "disabled", "reentry", "dv_survivor", \
"pregnant", "senior", or empty array. WHO the person IS, not what service \
they need. veteran = military. disabled = physical/cognitive disability. \
reentry = released from jail/prison. dv_survivor = domestic violence. \
"I'm a disabled veteran" → ["veteran", "disabled"]. Omit if not mentioned.
}

Rules:
- service_type is what the person is SEEKING, not what they mention in passing. \
"I lost my job last year, now I need food" → service_type is "food" not \
"employment". "I saw a doctor on TV" → null, not "medical".
- populations is WHO the person IS: "I'm a vet and need food" → service_type \
"food", populations ["veteran"]. "Just got out of Rikers, need a job" → \
service_type "employment", populations ["reentry"]. Do NOT confuse \
population with service type.
- "somewhere to stay", "roof over my head", "need a bed", "sleeping in my car", \
"got nowhere to go", "couch surfing", "got put out" → shelter
- "I'm starving", "haven't eaten", "need to feed my kids", "can I get a plate" → food
- "I need to wash up", "I stink", "take a bath" → personal_care
- "need meds", "my teeth hurt", "I need detox", "I think I'm pregnant" → medical
- "I need to make money", "who's hiring", "looking for a gig" → employment
- "help with my papers", "help with ICE" → legal
- For tone: "I'm broken", "crying all day", "what's the point", "I hate my life" → emotional. \
"this is useless", "smh", "whatever" → frustrated.
- For action: "bet", "aight", "word", "yea" → confirm_yes. \
"nah I'm good", "I'm good" → confirm_deny. \
"talk to a person", "transfer me" → escalation.
- location must be a real NYC location (borough, neighborhood). Do NOT \
extract non-NYC locations.
- If the message is casual chat with no service intent ("hey what's up", \
"how are you"), return all nulls.

Return ONLY the JSON object. No other text."""


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def classify_unified(message: str) -> Optional[dict]:
    """Classify a message using a single LLM call.

    Returns a dict with all classification dimensions, or None if the
    LLM call fails (so the caller can fall back to regex).

    Only call this when regex found no service_type AND no action AND
    no tone AND the message is 4+ words.
    """
    try:
        from app.llm.claude_client import get_client, CLASSIFICATION_MODEL

        client = get_client()
        if client is None:
            return None

        response = client.messages.create(
            model=CLASSIFICATION_MODEL,
            max_tokens=300,
            system=_UNIFIED_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()

        parsed = json.loads(raw)
        return _validate_result(parsed)

    except json.JSONDecodeError as e:
        logger.error(f"Unified classifier returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Unified LLM classification failed: {e}")
        return None


# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def _validate_result(data: dict) -> dict:
    """Validate and normalize the LLM response.

    Ensures all fields are present and have valid values. Invalid values
    are replaced with None rather than failing the entire classification.
    """
    result = {}

    # Service type
    svc = data.get("service_type")
    if isinstance(svc, str):
        svc = svc.lower().strip()
    result["service_type"] = svc if svc in _VALID_SERVICE_TYPES else None

    # Service detail
    detail = data.get("service_detail")
    result["service_detail"] = detail if isinstance(detail, str) and detail else None

    # Location
    loc = data.get("location")
    if isinstance(loc, str):
        loc = loc.lower().strip()
    result["location"] = loc if loc else None

    # Additional services — normalize to 3-tuples
    additional = data.get("additional_services", [])
    result["additional_services"] = []
    if isinstance(additional, list):
        for item in additional:
            if isinstance(item, dict):
                a_svc = item.get("type", "")
                a_loc = item.get("location")
                if a_svc.lower() in _VALID_SERVICE_TYPES:
                    result["additional_services"].append(
                        (a_svc.lower(), None, a_loc)
                    )

    # Tone
    tone = data.get("tone")
    if isinstance(tone, str):
        tone = tone.lower().strip()
    result["tone"] = tone if tone in _VALID_TONES else None

    # Action
    action = data.get("action")
    if isinstance(action, str):
        action = action.lower().strip()
    result["action"] = action if action in _VALID_ACTIONS else None

    # Urgency
    urgency = data.get("urgency")
    if isinstance(urgency, str):
        urgency = urgency.lower().strip()
    result["urgency"] = urgency if urgency in _VALID_URGENCIES else None

    # Age
    age = data.get("age")
    if isinstance(age, int) and 0 < age < 120:
        result["age"] = age
    elif isinstance(age, str):
        try:
            age_int = int(age)
            result["age"] = age_int if 0 < age_int < 120 else None
        except ValueError:
            result["age"] = None
    else:
        result["age"] = None

    # Family status
    family = data.get("family_status")
    if isinstance(family, str):
        family = family.lower().strip()
    result["family_status"] = family if family in _VALID_FAMILY else None

    # Gender
    _VALID_GENDERS = {"male", "female", "transgender", "nonbinary", "lgbtq", None}
    gender = data.get("gender")
    if isinstance(gender, str):
        gender = gender.lower().strip()
    result["_gender"] = gender if gender in _VALID_GENDERS else None

    # Populations
    _VALID_POPULATIONS = {"veteran", "disabled", "reentry", "dv_survivor", "pregnant", "senior"}
    raw_pops = data.get("populations") or []
    if isinstance(raw_pops, list):
        result["_populations"] = sorted(
            p.lower().strip() for p in raw_pops
            if isinstance(p, str) and p.lower().strip() in _VALID_POPULATIONS
        )
    else:
        result["_populations"] = []

    return result
