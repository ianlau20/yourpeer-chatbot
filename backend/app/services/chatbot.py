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
from app.services.post_results import classify_post_results_question, answer_from_results


# ---------------------------------------------------------------------------
# CONTRACTION NORMALIZATION (P4 audit)
# ---------------------------------------------------------------------------
# Expands common contractions to their full forms so phrase lists only need
# the expanded version (e.g., "not helpful") to match all contraction
# variants ("isn't helpful", "isnt helpful", "wasn't helpful", etc.).
#
# Applied to frustration, emotional, and confused matching in _classify_tone.
# NOT applied to crisis detection — crisis uses explicit enumeration for safety.

_CONTRACTION_MAP = {
    # Negative contractions → "not" form
    "isn't": "is not", "isnt": "is not",
    "wasn't": "was not", "wasnt": "was not",
    "aren't": "are not", "arent": "are not",
    "weren't": "were not", "werent": "were not",
    "doesn't": "does not", "doesnt": "does not",
    "didn't": "did not", "didnt": "did not",
    "don't": "do not", "dont": "do not",
    "can't": "can not", "cant": "can not",
    "won't": "will not", "wont": "will not",
    "hasn't": "has not", "hasnt": "has not",
    "haven't": "have not", "havent": "have not",
    "wouldn't": "would not", "wouldnt": "would not",
    "couldn't": "could not", "couldnt": "could not",
    "shouldn't": "should not", "shouldnt": "should not",
    # Pronoun contractions
    "i'm": "i am", "im": "i am",
    "i've": "i have", "ive": "i have",
    "i'll": "i will",
    "i'd": "i would",
    "it's": "it is",
    "that's": "that is",
    "there's": "there is",
    "what's": "what is",
    "you're": "you are", "youre": "you are",
    "they're": "they are", "theyre": "they are",
    "we're": "we are",
}

# Sort by length descending so longer contractions match first
# ("wouldn't" before "won't" to avoid partial replacement)
_CONTRACTION_PAIRS = sorted(_CONTRACTION_MAP.items(), key=lambda x: -len(x[0]))


def _normalize_contractions(text: str) -> str:
    """Expand contractions for consistent phrase matching.

    Applied to frustration/emotional/confused matching so phrase lists
    only need the 'not' form to catch all contraction variants.

    NOT applied to crisis detection (explicit enumeration is safer).

    Example:
        "that wasn't helpful" → "that was not helpful"
        "I'm struggling"     → "I am struggling"
        "doesnt work"        → "does not work"
    """
    result = text.lower()
    for contraction, expansion in _CONTRACTION_PAIRS:
        result = result.replace(contraction, expansion)
    return result


# ---------------------------------------------------------------------------
# INTENSIFIER STRIPPING
# ---------------------------------------------------------------------------
# Removes common intensifier adverbs that break substring contiguity in
# phrase matching. "I'm really scared" → "I'm scared" matches "i'm scared".
#
# Applied alongside contraction normalization in _classify_tone.
# NOT applied to crisis detection — explicit enumeration is safer.

_INTENSIFIERS = {
    "really", "very", "so", "super", "extremely", "pretty", "quite",
    "totally", "absolutely", "incredibly", "truly", "deeply",
    "terribly", "horribly", "awfully", "genuinely", "particularly",
    "just", "kinda", "sorta",
}

_INTENSIFIER_RE = re.compile(
    r'\b(' + '|'.join(re.escape(w) for w in sorted(_INTENSIFIERS, key=len, reverse=True)) + r')\b\s*',
    re.IGNORECASE,
)


def _strip_intensifiers(text: str) -> str:
    """Remove common intensifiers for consistent phrase matching.

    "I'm really scared"      → "I'm scared"
    "I'm so incredibly down" → "I'm down"
    "feeling pretty hopeless" → "feeling hopeless"
    """
    result = _INTENSIFIER_RE.sub('', text)
    return re.sub(r'\s{2,}', ' ', result).strip()


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
    "what can you do", "how does this work",
    "what is this", "who are you", "what do you do",
    "how do i use this", "instructions",
    "what services", "what other services", "what else",
    "what do you offer", "what can i search for",
    "list services", "show services", "available services",
]

# "help" needs word-boundary matching to avoid colliding with
# "helpful", "unhelpful", "not helpful" (which are frustration phrases).
_HELP_WORD_RE = re.compile(r"\bhelp\b", re.IGNORECASE)

_ESCALATION_PHRASES = [
    "peer navigator", "talk to a person", "talk to someone",
    "speak to someone", "speak to a person", "real person",
    "human", "connect me", "connect with person",
    "connect with peer navigator", "call someone", "live chat",
    "case manager", "social worker", "counselor",
    # Missing variants (regex audit — 50% miss rate)
    "speak with someone", "speak with a person",
    "talk to a human", "speak to a human",
    "transfer me", "can someone call me",
    "person i can call", "someone to call",
    "is there a person", "actual person",
    "get me a person", "real human",
]

_FRUSTRATION_PHRASES = [
    "not helpful", "isn't helpful", "isnt helpful",
    "wasn't helpful", "wasnt helpful", "wasn't useful", "wasnt useful",
    "doesn't help", "doesnt help", "didn't help", "didnt help",
    "still not helpful", "still not useful", "still not working",
    "already tried", "tried that", "tried those",
    "none of those", "none of them", "doesn't work",
    "doesnt work", "didn't work", "didnt work",
    "useless", "waste of time", "not working",
    "can't find anything", "cant find anything",
    "not what i needed", "not what i need",
    "wrong results", "results are bad", "results are wrong",
    "thats not right", "that's not right", "thats wrong", "that's wrong",
    "not useful", "this sucks", "so unhelpful",
    # Missing contraction variants (P2 audit)
    "hasn't helped", "hasnt helped",
    "isn't working", "isnt working",
    "isn't useful", "isnt useful",
    "can't help me", "cant help me",
    "won't work", "wont work",
    # Stronger frustration / directed at bot (P2 audit)
    "this is ridiculous", "this is stupid",
    "you're not listening", "youre not listening",
    "you don't understand", "you dont understand",
    "same thing every time",
    "i keep getting the same results",
    # Resignation (P2 audit — route to frustration handler, not reset)
    "forget it", "this is pointless",
    # Informal / vernacular frustration (regex audit)
    "you're no help", "youre no help", "no help at all",
    "going in circles", "keep going in circles",
    "keeps asking the same thing", "asking me the same thing",
    "this is bs", "this is bull",
    "whatever",
    "smh",
    "bruh", "this ain't working", "this aint working",
    "yo this trash", "this is trash",
]

# Emotional expressions — sub-crisis distress that deserves warm
# acknowledgment rather than a service menu or a steer-back response.
# These must NOT overlap with service keywords ("feeling hungry" → service).
_EMOTIONAL_PHRASES = [
    "feeling down", "feeling really down",
    "really down", "so down",
    "feeling sad", "feeling really sad",
    "feeling bad", "feeling really bad",
    "feeling depressed", "so depressed", "really depressed", "very depressed",
    "feeling scared", "feeling really scared", "im scared", "i'm scared",
    "really scared", "so scared", "very scared",
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
    "i'm stressed", "im stressed",
    # Adjective forms — users describe their SITUATION as emotional
    # ("this is depressing") rather than their STATE ("I'm depressed").
    "depressing", "overwhelming", "terrifying", "heartbreaking",
    "i'm struggling", "im struggling",
    "tired of everything", "exhausted",
    "i just need someone to talk to", "just need to talk",
    "nobody cares", "no one cares",
    # "i'm X" / "im X" forms — needed since intensifiers break contiguity.
    # "I'm really sad" needs "i'm sad" in the list for stripped matching.
    "i'm sad", "im sad",
    "i'm down", "im down",
    "i'm anxious", "im anxious",
    "i'm lonely", "im lonely",
    "i'm hopeless", "im hopeless",
    "i'm depressed", "im depressed",
    "i'm stuck", "im stuck",
    # Shame / stigma (P1 audit — #1 barrier to help-seeking in this population)
    "embarrassed to ask", "ashamed to ask", "ashamed of myself",
    "embarrassed to be here", "feel like a failure",
    "never thought i'd need help", "never thought id need help",
    "never thought i'd need a food bank",
    "i'm pathetic", "im pathetic", "ashamed",
    # Grief / loss (P2 audit — common trigger for homelessness)
    "lost someone", "someone died", "my friend died",
    "grieving", "in mourning",
    # Post-normalization variants — _normalize_contractions() expands
    # "I'm" → "I am", so these forms must be in the list too.
    # Without them, "I'm scared" → normalized "I am scared" → no match.
    "i am scared", "i am feeling scared", "i feel scared",
    "i am sad", "i am feeling sad", "i feel sad",
    "i am down", "i am feeling down", "i feel down",
    "i am anxious", "i am feeling anxious", "i feel anxious",
    "i am lonely", "i am feeling lonely", "i feel lonely",
    "i am hopeless", "i am feeling hopeless", "i feel hopeless",
    "i am depressed", "i am feeling depressed", "i feel depressed",
    "i am stuck", "i am feeling stuck", "i feel stuck",
    "i am not okay", "i am not ok",
    "i am struggling", "i am pathetic",
    "i am stressed",
    # Isolation (P2 audit — major factor in homeless population)
    "nobody understands", "no one understands",
    "completely alone", "i have no one",
    "no friends", "no family",
    # Despair without suicidality (P2 audit)
    "everything is falling apart", "my life is falling apart",
    "nothing ever works out", "things keep getting worse",
    "i can't catch a break", "i cant catch a break",
    # Indirect emotional expressions (regex audit — 0% detection rate)
    "can't take it anymore", "cant take it anymore",
    "i just cant take it", "i just can't take it",
    "at the end of my rope", "end of my rope",
    "crying all day", "been crying",
    "i hate my life", "hate my life",
    "i have nothing", "have nothing left", "nothing left",
    "whats the point", "what's the point",
    "i feel broken", "im broken", "i'm broken", "i am broken",
    "feel empty", "feel empty inside",
    "feel like giving up", "giving up",
    "so hard right now", "everything is so hard",
    "i don't know what to do with myself",
    "dont know what to do with myself",
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
    # Additional privacy phrases (synced with bot_knowledge topics)
    "what happens to my", "what do you do with my",
    "where does my information", "where does my data",
    "is my information", "is my data",
    "do you sell", "do you keep",
    # Privacy questions that might co-occur with service keywords
    # (e.g., "If I search for shelter, do they get my info?")
    "do they get my information", "do they get my data",
    "do they know i searched", "does the shelter know",
    "does the provider", "who sees my", "who gets my",
    "will they know", "can they see my", "shared with",
    "is this anonymous", "is this confidential",
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
    "i'm lost", "im lost", "so lost",
    "i'm overwhelmed", "im overwhelmed", "so overwhelmed",
    "i'm not sure", "im not sure",
    "where do i start", "where do i begin",
    "what are my options", "what can i do",
    # Expanded confusion/overwhelm (P3 audit)
    "where do i even go", "who do i talk to",
    "this is confusing", "too many options",
    "everything is too much", "it's all too much",
    "i can't think straight", "i cant think straight",
    "so much going on",
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
    "yes", "yeah", "yea", "yep", "yup", "sure", "ok", "okay", "correct",
    "right", "go", "please", "do it", "find",
    # NYC youth slang / informal affirmation
    "bet", "aight", "ight", "word", "fasho", "fo sho",
    "facts", "say less", "cool", "def", "absolutely",
]

# Longer phrases that can use STARTS-WITH or CONTAINS matching
_CONFIRM_YES_STARTSWITH = [
    "yes ", "yeah ", "yea ", "yep ", "sure ", "ok ",
    "go ahead", "looks good", "looks right", "looks correct",
    "that's right", "thats right", "that's correct", "thats correct",
    "search for", "please search", "do the search",
    "yes search", "yes please",
    "confirm", "confirmed",
    # Informal / conversational
    "that works", "sounds good", "sounds right", "sounds correct",
    "lets go", "let's go", "for sure",
    "yea search", "bet ", "aight ",
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
    "no thanks", "no thank you",
    # Narrowed: "i don't want" was too broad — matched "I don't want
    # anyone to know" (shame context). Adding "to" or "that" suffix.
    "i dont want to", "i don't want to",
    "i dont want that", "i don't want that",
    "not right now", "maybe later", "changed my mind",
    "i changed my mind",
    # Informal declines (multi_decline_with_different_phrasing)
    "i'm good", "im good", "nah i'm good", "nah im good",
    "all good", "no need",
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

    # Correction — user tells us we misunderstood
    _CORRECTION_PHRASES = [
        "not what i meant", "not what i asked", "that's not what i",
        "thats not what i", "you misunderstood", "you got it wrong",
        "wrong thing", "i didn't ask for that", "i didnt ask for that",
        "i didn't mean", "i didnt mean", "that's wrong", "thats wrong",
        "try again", "no that's not right", "no thats not right",
    ]
    _CORRECTION_EXACT = ["no", "wrong", "nope"]
    # Only match exact corrections when there's a _last_action suggesting
    # the bot just did something the user is rejecting
    for phrase in _CORRECTION_PHRASES:
        if phrase in cleaned:
            return "correction"

    # Negative preference — user rejects all offered options
    _NEGATIVE_PREFERENCE_PHRASES = [
        "not what i want", "not what i need", "not what i am looking for",
        "i do not want any of those", "i dont want any of those",
        "i don't want any of those",
        "none of those", "none of these", "not interested in any",
        "that is not helpful", "those are not helpful",
        "those don't help", "those dont help",
        "none of them work", "none of those work",
        "i need something else", "something different",
        "those aren't what i need", "those arent what i need",
        # Experience-based rejection — user has tried the results
        "been to all of those", "been to all of them",
        "tried all of those", "tried them all", "tried all of them",
        "i don't like those", "i dont like those",
        "don't like those options", "dont like those options",
        "don't like any of those", "dont like any of those",
        "turned me away", "was really unsafe", "had a bad experience",
        "already been there", "i've been there", "ive been there",
    ]
    for phrase in _NEGATIVE_PREFERENCE_PHRASES:
        if phrase in cleaned:
            return "negative_preference"

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

    # Help — word-boundary check for "help" to avoid "helpful"/"unhelpful"
    if _HELP_WORD_RE.search(cleaned):
        # Exclude frustration phrases that contain "help" as a word
        # e.g., "doesn't help", "didn't help", "not helpful"
        # These should fall through to frustration handling, not help.
        # Check both original and normalized to catch all contraction forms.
        _help_negators = ["not help", "did not help", "does not help",
                          "will not help", "never help", "can not help",
                          "was not help", "has not help"]
        normalized = _normalize_contractions(cleaned)
        if not any(neg in cleaned for neg in _help_negators) and \
           not any(neg in normalized for neg in _help_negators):
            return "help"
    for phrase in _HELP_PHRASES:
        if phrase in cleaned:
            return "help"

    return None


_URGENT_PHRASES = [
    "right now", "tonight", "immediately", "asap", "urgent",
    "emergency", "before dark", "freezing",
    "nowhere to go", "have nowhere", "on the street",
    "please help", "please hurry", "desperate",
    "kicked out today", "evicted today",
]


_CRISIS_NOT_CHECKED = object()  # sentinel: caller hasn't run detect_crisis yet


def _classify_tone(text: str, crisis_result=_CRISIS_NOT_CHECKED) -> str | None:
    """Classify a message's emotional tone (how the user FEELS).

    No service-word gating — always runs. The caller decides how to
    combine tone with service intent.

    Args:
        text: The user's message.
        crisis_result: Pre-computed result from detect_crisis().
            Pass the return value directly (a tuple for crisis, None for
            no crisis). When omitted, _classify_tone calls detect_crisis
            itself. This avoids a redundant Sonnet LLM call when the
            caller has already checked.

    Returns one of: "crisis", "emotional", "frustrated", "confused",
    "urgent", or None.

    Priority order matters — crisis > frustrated > emotional > confused > urgent.
    Urgent is lowest because it's about speed, not emotion. When a stronger
    tone is present ("I'm scared and need shelter tonight"), empathy matters
    more than acknowledging urgency (which the urgency slot already captures).
    """
    lower = text.lower().strip()
    cleaned = re.sub(r"[^\w\s']", "", lower).strip()

    # Normalized form expands contractions so phrase lists only need
    # the "not" form (e.g., "not helpful") to match "isn't helpful",
    # "wasnt helpful", etc. Applied to frustration/emotional/confused only.
    # Crisis detection uses its own explicit enumeration for safety.
    normalized = _normalize_contractions(cleaned)

    # Stripped forms remove intensifiers so phrase lists don't need
    # every intensifier×emotion combination.
    # "I'm really scared" → stripped → "I'm scared" matches "i'm scared".
    stripped = _strip_intensifiers(cleaned)
    stripped_normalized = _strip_intensifiers(normalized)

    # Crisis — highest priority (uses original text, NOT normalized)
    # Use pre-computed result if available to avoid a redundant LLM call.
    if crisis_result is _CRISIS_NOT_CHECKED:
        crisis_result = detect_crisis(text)
    if crisis_result is not None:
        return "crisis"

    # Frustration — check all variants
    for phrase in _FRUSTRATION_PHRASES:
        if phrase in cleaned or phrase in normalized or phrase in stripped or phrase in stripped_normalized:
            return "frustrated"

    # Emotional — check all variants
    for phrase in _EMOTIONAL_PHRASES:
        if phrase in cleaned or phrase in normalized or phrase in stripped or phrase in stripped_normalized:
            return "emotional"

    # Confused — check all variants
    for phrase in _CONFUSED_PHRASES:
        if phrase in cleaned or phrase in normalized or phrase in stripped or phrase in stripped_normalized:
            return "confused"

    # Urgent — time pressure or panic without a stronger emotional tone.
    # Bridges from the urgency slot extractor's "high" phrases, plus
    # panic-specific phrases not covered by emotional/crisis.
    for phrase in _URGENT_PHRASES:
        if phrase in cleaned:
            return "urgent"

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
    # Check all variants: original, normalized, and intensifier-stripped.
    normalized = _normalize_contractions(cleaned)
    stripped = _strip_intensifiers(cleaned)
    stripped_normalized = _strip_intensifiers(normalized)
    for phrase in _FRUSTRATION_PHRASES:
        if phrase in cleaned or phrase in normalized or phrase in stripped or phrase in stripped_normalized:
            return "frustration"

    # Check slots — if service intent found, it wins over emotional/confused
    extracted = extract_slots(text)
    has_slot = any(v is not None for k, v in extracted.items()
                   if k != "additional_services")
    if has_slot:
        return "service"

    # Emotional / confused / urgent (only when no service intent)
    tone = _classify_tone(text)
    if tone == "emotional":
        return "emotional"
    if tone == "confused":
        return "confused"
    # Urgent without service intent is not actionable on its own —
    # it only matters as a prefix modifier in the service flow.
    # Map to "general" so LLM can try to interpret the message.
    # (Don't return "urgent" — no handler exists for that category.)

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
    "Or if there's something specific I can help you find, just let me know. "
    "I'm here."
)

# Emotion-specific static responses — each acknowledges the specific
# feeling WITHOUT mentioning services. The judge consistently flags
# service mentions in emotional responses as "too transactional."
_EMOTIONAL_RESPONSES = {
    "scared": (
        "It's okay to feel scared — that's a completely understandable "
        "reaction to what you're going through. You're not alone in this.\n\n"
        "If you'd like to talk to someone, I can connect you with a peer "
        "navigator who can help you figure out next steps. No pressure."
    ),
    "sad": (
        "I'm sorry you're feeling this way. It takes courage to say that, "
        "and it's okay to not be okay right now.\n\n"
        "If you'd like to talk to someone who understands, I can connect "
        "you with a peer navigator. I'm here whenever you're ready."
    ),
    "rough_day": (
        "That sounds really hard. Some days are just heavy, and it's "
        "okay to feel that way.\n\n"
        "If you'd like to talk to someone, I can connect you with a peer "
        "navigator. Or just take your time — I'm here."
    ),
    "shame": (
        "You have nothing to be ashamed of. A lot of people use these "
        "services — it doesn't say anything about you as a person.\n\n"
        "It takes real strength to reach out, and I'm glad you did. "
        "I'm here to help however I can."
    ),
    "grief": (
        "I'm really sorry for your loss. That's an incredibly heavy "
        "thing to carry.\n\n"
        "If you'd like to talk to someone, I can connect you with a peer "
        "navigator. There's no rush — I'm here."
    ),
    "alone": (
        "I hear you, and I'm sorry you're feeling that way. You're not "
        "invisible, and reaching out here took courage.\n\n"
        "If you'd like to talk to someone who understands, I can connect "
        "you with a peer navigator. I'm here."
    ),
}


def _pick_emotional_response(text: str) -> str:
    """Pick the most appropriate emotion-specific static response.

    Falls back to the generic _EMOTIONAL_RESPONSE if no specific
    emotion is detected. This provides better acknowledgment
    than a one-size-fits-all response.
    """
    lower = text.lower()

    # Shame/stigma
    if any(p in lower for p in [
        "embarrassed", "ashamed", "pathetic", "failure",
        "never thought i'd need", "never thought id need",
        "don't want anyone to know", "dont want anyone to know",
    ]):
        return _EMOTIONAL_RESPONSES["shame"]

    # Grief/loss
    if any(p in lower for p in [
        "died", "passed away", "lost someone", "grieving", "mourning",
    ]):
        return _EMOTIONAL_RESPONSES["grief"]

    # Scared/fear
    if any(p in lower for p in [
        "scared", "afraid", "frightened", "terrified", "fear",
    ]):
        return _EMOTIONAL_RESPONSES["scared"]

    # Isolation/loneliness
    if any(p in lower for p in [
        "alone", "no one", "nobody", "no friends", "no family",
        "have no one", "completely alone",
    ]):
        return _EMOTIONAL_RESPONSES["alone"]

    # Sad/down
    if any(p in lower for p in [
        "feeling down", "feeling sad", "feeling bad", "depressed",
        "not okay", "not ok", "not doing well", "not doing good",
        "i'm sad", "im sad", "i am sad",
    ]):
        return _EMOTIONAL_RESPONSES["sad"]

    # Rough day / general hardship
    if any(p in lower for p in [
        "rough day", "bad day", "tough day", "hard day",
        "rough time", "hard time", "tough time",
        "falling apart", "getting worse",
    ]):
        return _EMOTIONAL_RESPONSES["rough_day"]

    return _EMOTIONAL_RESPONSE


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

    # "near your location" reads naturally without "in", but borough/
    # neighborhood names need "in" ("in Brooklyn", "in Harlem").
    if location.startswith("near "):
        location_phrase = location
    else:
        location_phrase = f"in {location}"

    # Build the service label, including co-located services
    queued = slots.get("_queued_services", [])
    if queued:
        co_labels = [
            (q[1] if len(q) > 1 and q[1] else None) or _SERVICE_LABELS.get(q[0], q[0])
            for q in queued
        ]
        all_labels = [service_label] + co_labels
        if len(all_labels) == 2:
            service_label = f"{all_labels[0]} and {all_labels[1]}"
        else:
            service_label = ", ".join(all_labels[:-1]) + f", and {all_labels[-1]}"

    parts = [f"I'll search for {service_label} {location_phrase}"]
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
            {"label": "Staten Island", "value": "Staten Island"},
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
    from app.services.bot_knowledge import build_capability_context

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

    # Facts sourced from live code via bot_knowledge
    facts = build_capability_context()

    return (
        "You are YourPeer, a friendly assistant that helps people find "
        "free social services in New York City.\n\n"
        "The user is asking a question about how you work or what you can do. "
        "Answer their SPECIFIC question directly and honestly. Do not give a "
        "generic overview unless they asked for one.\n\n"
        f"{context_section}"
        f"{facts}\n\n"
        "Keep your response to 2-3 sentences. Answer the specific question. "
        "Be honest about limitations.\n\n"
        f"User question: {user_message}"
    )


def _static_bot_answer(message: str) -> str:
    """Pattern-matched answers for common bot questions when LLM is unavailable."""
    # Try bot_knowledge topic matching first (richer, maintained centrally)
    try:
        from app.services.bot_knowledge import answer_question
        knowledge_answer = answer_question(message)
        if knowledge_answer:
            return knowledge_answer
    except Exception:
        pass  # Fall through to legacy pattern matching

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
    # NOTE: "ice" uses word-boundary regex because it's a substring of "police"
    _ice_words = ["immigration", "deport", "undocumented", "immigrant"]
    _ice_re = re.compile(r'\bice\b', re.IGNORECASE)
    if any(w in lower for w in _ice_words) or _ice_re.search(lower):
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
    # Regex runs first (instant). If regex finds no service_type on a
    # message that's long enough to be a real request, the LLM extractor
    # runs to catch natural phrasings like "somewhere to stay" → shelter
    # or "help finding work" → employment that regex misses.
    early_extracted = extract_slots(message)
    has_service_intent = early_extracted.get("service_type") is not None

    # --- LLM SLOT ENRICHMENT (before classification) ---
    # When regex found no service_type, try the LLM extractor. This
    # is the fix for multi_reentry_shelter_employment (2.25) and
    # multi_dycd_rhy_youth_runaway (3.12) — the LLM prompt already
    # handles "got out of Rikers" → shelter, "ran away" + "somewhere
    # to stay" → shelter, "help finding work" → employment. It just
    # never got to run because routing pre-empted it.
    #
    # Gate: only run when it's likely to help and won't waste a call.
    # Skip for short messages (confirmations, greetings) and for
    # messages where an action was already detected that should take
    # priority (resets, bot questions, etc.).
    _action_pre = _classify_action(message)
    _SKIP_LLM_ENRICHMENT_ACTIONS = {
        "reset", "greeting", "thanks", "bot_identity", "bot_question",
        "confirm_yes", "confirm_deny", "confirm_change_service",
        "confirm_change_location", "correction", "negative_preference",
        "escalation",
    }
    if (_USE_LLM
            and not has_service_intent
            and len(message.split()) >= 5
            and _action_pre not in _SKIP_LLM_ENRICHMENT_ACTIONS):
        try:
            _llm_extracted = extract_slots_smart(message)
            if _llm_extracted.get("service_type"):
                logger.info(
                    f"LLM enrichment found service_type="
                    f"'{_llm_extracted['service_type']}' that regex missed"
                )
                early_extracted = _llm_extracted
                has_service_intent = True
        except Exception as e:
            logger.error(f"LLM slot enrichment failed: {e}")
            # Fall through — regex result is still usable

    # --- CRISIS DETECTION (always runs before any other handler) ---
    # Safety: crisis detection MUST run before post-results, confirmation,
    # or any other handler. Eval scenario "crisis_after_results" (P10) found
    # that DV disclosures after search results were being missed when crisis
    # detection didn't run on every turn.
    #
    # Performance: for short, unambiguous safe actions ("yes", "start over",
    # "hello"), we skip the expensive Sonnet LLM call (~2-5s) and only run
    # the instant regex check. The regex catches explicit crisis language;
    # the LLM catches indirect phrasing — which doesn't appear in "yes".
    _is_safe_short = (
        _action_pre in (
            "confirm_yes", "confirm_deny", "confirm_change_service",
            "confirm_change_location", "reset", "greeting", "thanks",
            "bot_identity",
        )
        and len(message.split()) <= 4
    )
    _crisis_result = detect_crisis(message, skip_llm=_is_safe_short)

    # Crisis takes absolute priority — even over post-results questions
    if _crisis_result is not None:
        tone = "crisis"
    else:
        tone = _classify_tone(message, crisis_result=_crisis_result)

    if tone == "crisis":
        # Jump straight to crisis handling (below in routing section)
        pass
    else:
        # --- POST-RESULTS QUESTION CHECK ---
        # Only runs when crisis detection cleared the message as safe.
        # Handles follow-up questions about displayed services
        # deterministically — NO LLM, no hallucination risk.
        _last_results = existing.get("_last_results")
        _is_confirmation_action = _action_pre in (
            "confirm_change_service", "confirm_change_location",
            "confirm_yes", "confirm_deny", "reset", "greeting",
        )
        if _last_results and not has_service_intent and not _is_confirmation_action:
            # Frustration and negative preference about results should NOT be
            # handled by post-results — they need the empathetic handlers.
            # "That's not helpful, I already tried all those places" contains
            # result-reference words ("those places") but is frustration, not
            # a question about the results.
            _is_frustration_or_rejection = (
                tone == "frustrated"
                or _action_pre == "negative_preference"
                or _action_pre == "correction"
            )
            if _is_frustration_or_rejection:
                # Clear results and fall through to normal routing
                existing.pop("_last_results", None)
                save_session_slots(session_id, existing)
            elif early_extracted.get("location"):
                # If the user provided a new location, they're likely starting
                # a new search, not asking about displayed results.
                existing.pop("_last_results", None)
                save_session_slots(session_id, existing)
            else:
                # "Show all results" — re-display the stored results
                if message.lower().strip() in ("show all results", "show results", "show all"):
                    result = {
                        "session_id": session_id,
                        "response": "Here are all the results again:",
                        "follow_up_needed": False,
                        "slots": existing,
                        "services": _last_results,
                        "result_count": len(_last_results),
                        "relaxed_search": False,
                        "quick_replies": [
                            {"label": "🔍 New search", "value": "Start over"},
                            {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
                        ],
                    }
                    _log_turn(session_id, redacted_message, result, "post_results", request_id=request_id)
                    return result

                post_intent = classify_post_results_question(message)
                if post_intent is not None:
                    pr = answer_from_results(post_intent, _last_results)
                    if pr is not None:
                        result = {
                            "session_id": session_id,
                            "response": pr["response"],
                            "follow_up_needed": False,
                            "slots": existing,
                            "services": pr.get("services", []),
                            "result_count": len(pr.get("services", [])),
                            "relaxed_search": False,
                            "quick_replies": pr.get("quick_replies", []),
                        }
                        _log_turn(session_id, redacted_message, result, "post_results", request_id=request_id)
                        return result
                    # pr is None — name didn't match any result.
                    # Show disambiguation: let the user choose between
                    # searching for something new or asking about results.
                    if post_intent.get("type") == "specific_name":
                        query = post_intent.get("query", "that")
                        result = _empty_reply(
                            session_id,
                            f"I'm not sure if you're asking about the results "
                            f"I showed, or if you'd like to search for "
                            f"something new. Which would you prefer?",
                            existing,
                            quick_replies=[
                                {"label": f"🔍 Search for {query}", "value": f"I need {query}"},
                                {"label": "📋 More about results", "value": "Tell me about the first one"},
                                {"label": "🔍 New search", "value": "Start over"},
                            ],
                        )
                        _log_turn(session_id, redacted_message, result, "disambiguation",
                                  request_id=request_id, confidence="disambiguated")
                        return result
                    # Other post-results intents that returned None — fall through

        # If the user is starting a new action, clear stale results
        if _last_results and (has_service_intent or _is_confirmation_action):
            existing.pop("_last_results", None)
            save_session_slots(session_id, existing)

    # --- COMBINE INTO ROUTING CATEGORY ---
    # Priority: crisis > reset > confirmations > service intent > actions > tone > LLM > general
    action = _action_pre  # Already computed above (avoid duplicate call)
    _response_tone = tone  # stored for use in service flow framing
    _confidence = "high"   # default: regex match = high confidence

    if tone == "crisis":
        category = "crisis"
    elif action == "reset":
        category = "reset"
    elif action == "correction":
        category = "correction"
    elif action == "negative_preference":
        category = "negative_preference"
    elif action in ("confirm_change_service", "confirm_change_location",
                     "confirm_yes", "confirm_deny"):
        category = action
    elif action in ("bot_identity", "bot_question", "greeting", "thanks"):
        category = action
    elif has_service_intent:
        # Exception: privacy questions should NOT be overridden by service
        # intent. "If I search for shelter, do they get my info?" is a
        # privacy question, not a shelter request.
        if action == "bot_question":
            category = "bot_question"
        elif action == "escalation" and not early_extracted.get("location"):
            category = "escalation"
        else:
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
            _confidence = "medium"  # LLM classification
        else:
            category = "general"
            _confidence = "low"     # LLM failed, pure fallback
    else:
        category = "general"
        _confidence = "low"         # no regex match, no LLM

    # --- Crisis ---
    # Highest priority. Crisis resources are shown immediately.
    # The session is NOT cleared — the user may continue afterward.
    if category == "crisis":
        # Reuse the crisis result computed once above (before _classify_tone).
        # No need to call detect_crisis again.
        if _crisis_result is None:
            # Classification said crisis but detect_crisis disagrees
            # (e.g. LLM fail-open during classification but not during
            # the dedicated check). Treat as general conversation.
            category = "general"
        else:
            crisis_category, crisis_response = _crisis_result
            logger.warning(
                f"Session {session_id}: crisis detected, "
                f"category='{crisis_category}'"
            )
            log_crisis_detected(session_id, crisis_category, redacted_message, request_id=request_id)
            # Clear any pending confirmation — a user in crisis shouldn't
            # return to a search confirmation on their next message.
            if existing.get("_pending_confirmation"):
                existing.pop("_pending_confirmation", None)

            # Step-down: when the user has service intent AND the crisis
            # category is non-acute (safety_concern, domestic_violence),
            # show crisis resources but also preserve the service context
            # and offer to search. This handles cases like "I was kicked
            # out and need shelter in Brooklyn" where the crisis handler
            # fires on "kicked out" but the user also has a clear service
            # request that shouldn't be lost.
            _step_down_categories = ("safety_concern", "domestic_violence", "youth_runaway")
            if (has_service_intent
                    and crisis_category in _step_down_categories):
                # Merge early-extracted slots into session so they're
                # available when the user says "yes, search"
                merged_crisis = merge_slots(existing, early_extracted)
                # Store queued services if multi-intent
                additional = early_extracted.get("additional_services", [])
                if additional and "_queued_services" not in merged_crisis:
                    merged_crisis["_queued_services"] = additional
                merged_crisis["_last_action"] = "crisis"
                save_session_slots(session_id, merged_crisis)

                # Build the step-down offer
                svc_label = _SERVICE_LABELS.get(
                    early_extracted.get("service_type", ""),
                    early_extracted.get("service_type", "services"),
                )
                loc_label = early_extracted.get("location", "your area")
                step_down_msg = (
                    f"\n\nI can also help you find {svc_label} in "
                    f"{loc_label} — would you like me to search?"
                )
                result = _empty_reply(
                    session_id,
                    crisis_response + step_down_msg,
                    merged_crisis,
                    quick_replies=[
                        {"label": f"✅ Yes, search for {svc_label}",
                         "value": "Yes, search"},
                        {"label": "🤝 Peer navigator",
                         "value": "Connect with peer navigator"},
                    ],
                )
            else:
                # Acute crisis (suicide, medical, trafficking, violence)
                # or no service intent — show crisis resources only.
                existing["_last_action"] = "crisis"
                save_session_slots(session_id, existing)
                result = _empty_reply(session_id, crisis_response, existing)

            _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
            return result

    # --- Reset ---
    if category == "reset":
        clear_session(session_id)
        log_session_reset(session_id)
        result = _empty_reply(
            session_id, _RESET_RESPONSE, {},
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Correction ("not what I meant") ---
    if category == "correction":
        # Clear any state that led to the misunderstanding
        existing.pop("_pending_confirmation", None)
        existing.pop("_last_action", None)
        existing.pop("_last_results", None)
        save_session_slots(session_id, existing)
        # Build context-aware response
        service_type = existing.get("service_type")
        location = existing.get("location")
        context = ""
        if service_type and location:
            context = f" I was searching for {service_type} in {location}."
        elif service_type:
            context = f" I was searching for {service_type}."
        result = _empty_reply(
            session_id,
            f"Sorry about that!{context} Let me know what you need — you can "
            f"pick a service below, tell me in your own words, or connect "
            f"with a peer navigator.",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES) + [
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "correction",
                  request_id=request_id, tone=tone, confidence="low")
        return result

    # --- Negative preference ---
    if category == "negative_preference":
        # Acknowledge the rejection and offer alternative paths.
        existing["_last_action"] = "negative_preference"
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "I understand — those options aren't what you need. "
            "I can search for a different type of service, or connect "
            "you with a peer navigator who might know of other resources. "
            "What would be most helpful?",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES) + [
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "negative_preference",
                  request_id=request_id, tone=tone)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Thanks ---
    if category == "thanks":
        result = _empty_reply(
            session_id, _THANKS_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Help ---
    if category == "help":
        # No ad-hoc slot guard needed — if the message had service intent,
        # it was already routed to "service" category above.
        result = _empty_reply(
            session_id, _HELP_RESPONSE, existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Bot Identity ---
    if category == "bot_identity":
        result = _empty_reply(
            session_id, _BOT_IDENTITY_RESPONSE, existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Bot capability questions ---
    # "Why couldn't you get my location?", "What can you search for?"
    # Answer directly using LLM with a factual prompt about capabilities.
    if category == "bot_question":
        # Try bot_knowledge static answer first (topic-matched, no LLM needed)
        from app.services.bot_knowledge import answer_question, build_capability_context
        static_answer = answer_question(message)
        if static_answer:
            response = static_answer
        elif _USE_LLM:
            try:
                prompt = _build_bot_question_prompt(message, slots=existing)
                response = claude_reply(prompt)
            except Exception as e:
                logger.error(f"Bot question LLM response failed: {e}")
                response = _static_bot_answer(message)
        else:
            response = _static_bot_answer(message)
        result = _empty_reply(session_id, response, existing)
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Location unknown ---
    # When the bot just asked for location (service_type set, location missing)
    # and the user says "I don't know" / "not sure" / "idk", offer geolocation
    # and borough buttons instead of falling into the confused handler.
    _LOCATION_UNKNOWN_PHRASES = [
        "i don't know", "i dont know", "idk", "not sure", "i'm not sure",
        "im not sure", "no idea", "don't know", "dont know",
        "i don't know where i am", "i dont know where i am",
        "not sure where i am", "don't know where i am",
        "dont know where i am", "no clue",
        "anywhere", "wherever", "doesn't matter", "doesnt matter",
        "it doesn't matter", "it doesnt matter",
        "where i am",
    ]
    # Short phrases that need exact match to avoid substring collisions
    # (e.g., "here" inside "there", "nowhere", "here's what I need")
    _LOCATION_UNKNOWN_EXACT = ["here", "right here"]
    _msg_lower = message.lower().strip()
    _is_location_unknown = (
        any(p in _msg_lower for p in _LOCATION_UNKNOWN_PHRASES)
        or _msg_lower in _LOCATION_UNKNOWN_EXACT
    )
    if (existing.get("service_type")
            and not existing.get("location")
            and not existing.get("_pending_confirmation")
            and _is_location_unknown):
        result = _empty_reply(
            session_id,
            "No problem! You can share your location and I'll find what's "
            "nearby, or pick a borough:",
            existing,
            quick_replies=[
                {"label": "📍 Use my location", "value": "__use_geolocation__"},
                {"label": "Manhattan", "value": "Manhattan"},
                {"label": "Brooklyn", "value": "Brooklyn"},
                {"label": "Queens", "value": "Queens"},
                {"label": "Bronx", "value": "Bronx"},
                {"label": "Staten Island", "value": "Staten Island"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "location_unknown", request_id=request_id, tone=tone)
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
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Emotional expression ---
    # "I'm feeling really down", "having a rough day", "I'm scared"
    # Acknowledge the feeling warmly. Don't show service buttons unless
    # the user asks for something practical.
    if category == "emotional":
        # Static-first: use emotion-specific response — NO LLM call.
        # The LLM frequently steers toward service-finding mode despite
        # prompt instructions, and the judge flags this as "too transactional."
        # Static responses are verified to pass all eval criteria.
        response = _pick_emotional_response(message)

        # Track so "yes"/"no" on the next message refers to the peer
        # navigator offer, not a pending search confirmation.
        existing["_last_action"] = "emotional"
        save_session_slots(session_id, existing)

        result = _empty_reply(
            session_id, response, existing,
            quick_replies=[
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Frustration ---
    if category == "frustration":
        # Track frustration count — more robust than checking _last_action
        # since _last_action could be cleared by intermediate handlers.
        frust_count = existing.get("_frustration_count", 0) + 1
        existing["_frustration_count"] = frust_count
        existing["_last_action"] = "frustration"
        save_session_slots(session_id, existing)

        if frust_count >= 3:
            # 3rd+ frustration — immediate navigator offer, very short
            result = _empty_reply(
                session_id,
                "I'm sorry I haven't been able to help. Let me connect you "
                "with a peer navigator — they can work with you directly.",
                existing,
                quick_replies=[
                    {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
                ],
            )
        elif frust_count >= 2:
            # Repeated frustration — shorter, more direct
            result = _empty_reply(
                session_id,
                "I hear you — I'm clearly not finding what you need right now. "
                "I think a peer navigator would be more helpful. They're real "
                "people who know the system and can work with you directly. "
                "You can also call 311 for live help anytime.",
                existing,
                quick_replies=[
                    {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
                    {"label": "🔄 Start over", "value": "Start over"},
                ],
            )
        else:
            result = _empty_reply(
                session_id, _FRUSTRATION_RESPONSE, existing,
                quick_replies=[
                    {"label": "🔍 New search", "value": "Start over"},
                    {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
                ],
            )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
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
        result = _empty_reply(
            session_id, _ESCALATION_RESPONSE, existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "👤 Talk to a person", "value": "Connect with person"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # --- Context-aware "yes" / "no" handling ---
    # After an escalation or emotional response, "yes" and "no" refer to the
    # peer navigator offer — not to a pending search confirmation.
    last_action = existing.get("_last_action")

    if last_action in ("escalation", "emotional") and category == "confirm_yes":
        # "Yes" after escalation or emotional = "yes, connect me with a person"
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id, _ESCALATION_RESPONSE, existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "👤 Talk to a person", "value": "Connect with person"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "escalation", request_id=request_id, tone=tone)
        return result

    if last_action == "crisis" and category == "confirm_yes":
        # "Yes" after crisis step-down = "yes, search for services"
        # The step-down handler preserved the extracted slots in session.
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        if is_enough_to_answer(existing):
            result = _execute_and_respond(session_id, message, existing, request_id=request_id)
        else:
            # Need more info — ask follow-up
            follow_up = next_follow_up_question(existing)
            result = _empty_reply(
                session_id, follow_up, existing,
                quick_replies=_follow_up_quick_replies(existing),
            )
            result["follow_up_needed"] = True
        _log_turn(session_id, redacted_message, result, "service", request_id=request_id, tone=tone)
        return result

    if last_action == "confused" and category == "confirm_yes":
        # "Yes" after confused = "yes, connect me with a person"
        # (the confused handler shows a "Talk to a person" button)
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id, _ESCALATION_RESPONSE, existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "👤 Talk to a person", "value": "Connect with person"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "escalation", request_id=request_id, tone=tone)
        return result

    if last_action == "frustration" and category == "confirm_yes":
        # "Yes" after frustration = "yes, connect me with a navigator"
        # The frustration handler's messaging pushes toward navigator
        # ("I think a peer navigator would be more helpful"). The "Try
        # different search" button sends "Start over" directly, so it
        # doesn't need this "yes" shortcut for resetting.
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id, _ESCALATION_RESPONSE, existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "👤 Talk to a person", "value": "Connect with person"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "escalation", request_id=request_id, tone=tone)
        return result

    if category == "confirm_deny" and last_action == "escalation":
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem — I'm here if you change your mind. "
            "Is there anything else I can help you with?",
            existing,
            quick_replies=[
                {"label": "🔍 New search", "value": "Start over"},
                {"label": "👤 Talk to a person", "value": "Connect with person"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id, tone=tone)
        return result

    if category == "confirm_deny" and last_action == "emotional":
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "That's okay. I'm here whenever you're ready. "
            "If there's anything practical I can help you find, just let me know.",
            existing,
            # Don't push the full service menu after someone expressed distress
            # and declined support — keep it gentle (AVR pattern).
            quick_replies=[
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id, tone=tone)
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
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id, tone=tone)
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
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id, tone=tone)
        return result

    if category == "confirm_deny" and last_action == "crisis":
        # "No" after crisis step-down = user doesn't want to search,
        # just needs the crisis resources that were already shown.
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "That's okay. The resources above are available anytime. "
            "If you'd like to search for services later, I'm here.",
            existing,
            quick_replies=[
                {"label": "🤝 Peer navigator", "value": "Connect with peer navigator"},
                {"label": "🔍 Search for services", "value": "I need help"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "general", request_id=request_id, tone=tone)
        return result

    # Clear the last_action tracker now that we've checked it
    if last_action:
        existing.pop("_last_action", None)
        save_session_slots(session_id, existing)

    # --- Handle "change location" / "change service" outside pending ---
    # These buttons appear in after-results quick replies and in various
    # contexts. Previously they only worked during pending confirmation,
    # causing a full restart when tapped after results were delivered.
    if not existing.get("_pending_confirmation"):
        if category == "confirm_change_location":
            existing["location"] = None
            save_session_slots(session_id, existing)
            result = _empty_reply(
                session_id,
                "Sure! What neighborhood or borough should I search in?",
                existing,
                quick_replies=[
                    {"label": "📍 Use my location", "value": "__use_geolocation__"},
                    {"label": "Manhattan", "value": "Manhattan"},
                    {"label": "Brooklyn", "value": "Brooklyn"},
                    {"label": "Queens", "value": "Queens"},
                    {"label": "Bronx", "value": "Bronx"},
                    {"label": "Staten Island", "value": "Staten Island"},
                ],
            )
            _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
            return result

        if category == "confirm_change_service":
            existing["service_type"] = None
            existing.pop("service_detail", None)
            save_session_slots(session_id, existing)
            result = _empty_reply(
                session_id,
                "No problem! What kind of help do you need?",
                existing,
                quick_replies=list(_WELCOME_QUICK_REPLIES),
            )
            _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
            return result

    # --- Handle confirmation responses ---
    pending = existing.get("_pending_confirmation")

    if pending and category == "confirm_yes":
        # User confirmed — clear the flag and execute the query.
        # But first check if the confirmation message itself contains a
        # DIFFERENT service type (e.g., "search for shelter" when pending
        # was for food). If so, update the slots before executing.
        confirm_extracted = extract_slots(message)
        if (confirm_extracted.get("service_type") is not None
                and confirm_extracted["service_type"] != existing.get("service_type")):
            logger.info(
                f"Service type changed in confirmation: "
                f"'{existing.get('service_type')}' → '{confirm_extracted['service_type']}'"
            )
            existing = merge_slots(existing, confirm_extracted)
        existing.pop("_pending_confirmation", None)
        save_session_slots(session_id, existing)
        result = _execute_and_respond(session_id, message, existing, request_id=request_id)
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
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
                {"label": "📍 Use my location", "value": "__use_geolocation__"},
                {"label": "Manhattan", "value": "Manhattan"},
                {"label": "Brooklyn", "value": "Brooklyn"},
                {"label": "Queens", "value": "Queens"},
                {"label": "Bronx", "value": "Bronx"},
                {"label": "Staten Island", "value": "Staten Island"},
            ],
        )
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # "No thanks" after a queue offer (no pending confirmation, but a queue
    # offer was shown). Handles both cases: remaining queue items OR a
    # single-item queue where the item was already popped at offer time.
    queue_offer_active = existing.get("_queued_services") or existing.get("_queue_offer_pending")
    if not pending and category == "confirm_deny" and queue_offer_active:
        existing.pop("_queued_services", None)
        existing.pop("_queue_offer_pending", None)
        existing.pop("_queued_services_original", None)
        save_session_slots(session_id, existing)
        result = _empty_reply(
            session_id,
            "No problem! Let me know if you need anything else.",
            existing,
            quick_replies=list(_WELCOME_QUICK_REPLIES),
        )
        _log_turn(session_id, redacted_message, result, "queue_decline", request_id=request_id, tone=tone)
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
            # Re-show the confirmation with a nudge, but acknowledge tone
            # if the user expressed emotion.
            existing["_pending_confirmation"] = True
            save_session_slots(session_id, existing)

            nudge_prefix = "Just to make sure — "
            if _response_tone == "emotional":
                nudge_prefix = "I hear you. Just to make sure — "
            elif _response_tone == "frustrated":
                nudge_prefix = "I understand. Let me just confirm — "
            elif _response_tone == "confused":
                nudge_prefix = "No worries — let me just confirm: "
            elif _response_tone == "urgent":
                nudge_prefix = "Got it — just to confirm: "

            confirm_msg = (
                nudge_prefix + _build_confirmation_message(existing)
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
            _log_turn(session_id, redacted_message, result, "confirmation_nudge", request_id=request_id, tone=tone)
            return result

        # Has new slot data — merge and re-process below

    # --- Service request or general conversation ---
    # Slots were extracted with regex (and possibly LLM enrichment) above.
    # For service-category messages, re-extract with LLM + conversation
    # history for best accuracy. This may re-run the LLM if enrichment
    # already ran, but the conversation_history context can improve results
    # in multi-turn scenarios. Cost: ~$0.001 for Haiku — negligible.
    # For non-service categories, use early_extracted to avoid LLM
    # hallucinating slots from conversation history.
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

    # Queue additional services for offering after the primary search.
    # Only set when new additional services are extracted — don't overwrite
    # an existing queue from a prior multi-intent message.
    additional = extracted.get("additional_services", [])
    if additional and "_queued_services" not in merged:
        merged["_queued_services"] = additional

    # If the user changed their service type, clear a stale queue
    # (e.g., they said "food and shelter" but then changed to "medical")
    if (extracted.get("service_type")
            and existing.get("service_type")
            and extracted["service_type"] != existing.get("service_type")
            and not additional):
        merged.pop("_queued_services", None)

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
    # expressed emotion alongside a service request. Uses category ==
    # "service" rather than has_service_intent so that LLM-detected
    # service intent (e.g., "I just got out of the hospital, I'm scared")
    # also gets the empathetic prefix.
    _is_service_flow = category == "service"
    _tone_prefix = ""
    if _response_tone == "emotional" and _is_service_flow:
        _tone_prefix = "I hear you, and I want to help. "
    elif _response_tone == "frustrated" and _is_service_flow:
        _tone_prefix = "I understand this has been frustrating. Let me try something different. "
    elif _response_tone == "confused" and _is_service_flow:
        _tone_prefix = "No worries — let me help you with that. "
    elif _response_tone == "urgent" and _is_service_flow:
        _tone_prefix = "I can see this is urgent — let me find something right away. "

    # If enough detail exists AND this message contributed new info,
    # go to CONFIRMATION step.
    if (is_enough_to_answer(merged) or _geolocation_ready) and has_new_slots:
        # Set pending confirmation flag
        merged["_pending_confirmation"] = True
        # Clear stale queue offer flag from previous search cycle
        merged.pop("_queue_offer_pending", None)
        merged.pop("_queued_services_original", None)
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
        _log_turn(session_id, redacted_message, result, "confirmation", request_id=request_id, tone=tone)
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
        _log_turn(session_id, redacted_message, result, category, request_id=request_id, tone=tone)
        return result

    # Service flow continuation: the user already has a service_type and
    # just provided new info (location, age, etc.) that wasn't classified
    # as a "service" message. For example, replying "near me" or "25" to
    # a follow-up question. Treat as service flow, not general conversation.
    if has_new_slots and existing.get("service_type") and not existing.get("_pending_confirmation"):
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
        _log_turn(session_id, redacted_message, result, "service", request_id=request_id, tone=tone)
        return result

    # --- General conversation ---
    # The message didn't match any service keywords and isn't a greeting/reset.

    # Casual chat detection — "how are you", "just wanted to chat" etc.
    # should get a warm conversational response WITHOUT service buttons.
    _CASUAL_CHAT_RE = re.compile(
        r"\b(how are you|how's it going|hows it going|what's up|whats up|"
        r"hey there|just (wanted to|wanna) (chat|talk)|having a good day|"
        r"good morning|good afternoon|good evening|how you doing|"
        r"what are you up to|how do you do)\b", re.I
    )
    _is_casual_chat = bool(_CASUAL_CHAT_RE.search(message))

    # If the user has a location but no service_type and we already asked
    # what they need, they may have requested something we can't help with
    # (e.g. "helicopter ride"). Redirect gracefully to real services.
    #
    # Also catch early-turn "I need X" requests where X doesn't map to any
    # known service type — even without a location or transcript history.
    _need_re = re.compile(
        r"\b(?:i need|i want|can you find|looking for|help me find|"
        r"get me|find me|i'm looking for|im looking for)\b",
        re.I,
    )
    _is_service_request_pattern = bool(_need_re.search(message))
    _has_unrecognized_need = (
        _is_service_request_pattern
        and not merged.get("service_type")
        and not _is_casual_chat
    )
    if (_has_unrecognized_need
            or (merged.get("location")
                and not merged.get("service_type")
                and len(merged.get("transcript", [])) >= 2)):
        location_label = merged.get("location", "your area")
        result = _empty_reply(
            session_id,
            "I'm not sure I can help with that specifically, but I can "
            f"search for services in {location_label} — things like food, "
            "shelter, clothing, showers, health care, legal help, and more. "
            "What would be most helpful?",
            merged,
            quick_replies=list(_WELCOME_QUICK_REPLIES) + [
                {"label": "❌ Not what I meant", "value": "not what I meant"},
            ],
        )
        _log_turn(session_id, redacted_message, result, "unrecognized_service",
                  request_id=request_id, tone=tone, confidence="low")
        return result

    # Use Claude Haiku for a natural conversational response.
    # Don't push service category buttons — they were shown on welcome.
    # The user can say "what can you help with" to see them again.

    # Casual chat gets a static response — the LLM tends to mention
    # services even with explicit "do NOT push services" in the prompt.
    if _is_casual_chat:
        _CASUAL_RESPONSES = [
            "I'm doing well, thanks for asking! I'm here whenever you need me.",
            "Hey! Just here and ready to help whenever you are.",
            "Doing good! Let me know if there's anything I can help you find.",
        ]
        # Pick based on transcript length for variety
        _idx = len(merged.get("transcript", [])) % len(_CASUAL_RESPONSES)
        response = _CASUAL_RESPONSES[_idx]
    else:
        response = _fallback_response(message, merged)
    has_service_intent = bool(
        merged.get("service_type") or merged.get("location")
    )
    # Build quick replies — add "Not what I meant" for LLM-routed responses
    # to let users recover from misinterpretation
    _general_qr = []
    if not has_service_intent and len(merged.get("transcript", [])) <= 1 and not _is_casual_chat:
        _general_qr = list(_WELCOME_QUICK_REPLIES)
    if _confidence in ("medium", "low"):
        _general_qr.append({"label": "❌ Not what I meant", "value": "not what I meant"})
    result = _empty_reply(
        session_id, response, merged,
        quick_replies=_general_qr,
    )
    _log_turn(session_id, redacted_message, result, "general",
              request_id=request_id, tone=tone, confidence=_confidence)
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

        # Extract co-located service types from the queue for combined search.
        # Instead of searching food first then offering shelter, try to find
        # locations that have BOTH food AND shelter.
        queued = slots.get("_queued_services", [])
        colocated_types = [q[0] for q in queued] if queued else None
        # Save original queue with detail labels before it gets cleared
        if queued:
            slots["_queued_services_original"] = list(queued)

        results = query_services(
            service_type=slots.get("service_type"),
            location=location,
            age=slots.get("age"),
            latitude=slots.get("_latitude") if use_coords else None,
            longitude=slots.get("_longitude") if use_coords else None,
            family_status=slots.get("family_status"),
            colocated_service_types=colocated_types,
        )

        # If co-located search succeeded, clear the queue — no need to offer
        # the additional services separately since results already have them.
        colocated_success = (
            colocated_types
            and results.get("result_count", 0) > 0
            and not results.get("colocated_fallback")
        )
        if colocated_success:
            slots.pop("_queued_services", None)
            slots.pop("_queued_services_original", None)
            save_session_slots(session_id, slots)

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

            if colocated_success and colocated_types:
                # Build a natural label for the combined services
                primary = _SERVICE_LABELS.get(
                    slots.get("service_type", ""), slots.get("service_type", "")
                )
                # Use the detail label from the queue if available (e.g. "dental care"
                # instead of "health care"), falling back to the service type label.
                queued_original = slots.get("_queued_services_original", [])
                co_labels = []
                for i, t in enumerate(colocated_types):
                    detail = queued_original[i][1] if i < len(queued_original) else None
                    co_labels.append(detail or _SERVICE_LABELS.get(t, t))
                all_labels = [primary] + co_labels
                combined = " and ".join(all_labels) if len(all_labels) <= 2 else (
                    ", ".join(all_labels[:-1]) + ", and " + all_labels[-1]
                )
                bot_response = (
                    f"I found {result_count} location(s) that offer both "
                    f"{combined.lower()}{qualifier}. "
                    f"Here's what's available:"
                )
            else:
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

    # Check for queued services from multi-intent extraction.
    # If the user said "I need food and shelter", food was searched first.
    # Now offer shelter.
    queued = slots.get("_queued_services", [])
    if queued and services_list:
        q_item = queued[0]
        next_service = q_item[0]
        next_detail = q_item[1] if len(q_item) > 1 else None
        next_location = q_item[2] if len(q_item) > 2 else None
        remaining = queued[1:]

        # Update session: pop the offered service, keep remaining.
        # Set _queue_offer_pending so the decline handler fires even
        # when this was the last queued item.
        if remaining:
            slots["_queued_services"] = remaining
        else:
            slots.pop("_queued_services", None)
        slots["_queue_offer_pending"] = True

        # If the queued service has a different location, store it
        # so the search uses the right location when accepted.
        if next_location and next_location != slots.get("location"):
            slots["_queued_location"] = next_location
        save_session_slots(session_id, slots)

        label = next_detail or _SERVICE_LABELS.get(next_service, next_service)
        loc_suffix = ""
        if next_location and next_location != slots.get("location"):
            loc_suffix = f" in {next_location}"
        bot_response += (
            f"\n\nYou also mentioned {label}{loc_suffix} — would you like me to "
            f"search for that too?"
        )
        # Include location in the quick reply value so slot extraction picks it up
        qr_value = f"I need {next_service}"
        if next_location:
            qr_value += f" in {next_location}"
        after_results_qr = [
            {"label": f"✅ Yes, search for {label}", "value": qr_value},
            {"label": "❌ No thanks", "value": "No thanks"},
        ]

    # Store results in session so post-results questions can reference them.
    # Only stored when we actually have results to show.
    if services_list:
        slots["_last_results"] = services_list
        save_session_slots(session_id, slots)

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

def _log_turn(session_id: str, user_msg: str, result: dict, category: str,
              request_id: str | None = None, tone=None, confidence: str = "high"):
    """Log a conversation turn to the audit log.

    Args:
        confidence: "high" (regex match), "medium" (LLM classification),
                    "low" (fallback/ambiguous), "disambiguated" (user was asked to clarify)
    """
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
            tone=tone,
            confidence=confidence,
        )
    except Exception as e:
        logger.error(f"Failed to log conversation turn: {e}")
