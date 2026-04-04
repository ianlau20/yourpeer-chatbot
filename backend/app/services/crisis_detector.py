"""
Crisis Detection Module

Detects crisis language in user messages and returns the appropriate
category and response. This runs BEFORE all other message classification
in the chatbot — a message containing crisis language always gets crisis
resources, never a slot-filling follow-up.

Categories (from the architecture spec §5.3):
    1. Suicide / self-harm
    2. Violence / harm to others
    3. Domestic violence / abuse
    4. Exploitation / trafficking
    5. Medical emergency

Design decisions:
    - Keyword-based, not LLM-based, so it's deterministic and auditable.
    - Errs on the side of false positives — showing crisis resources to
      someone who doesn't need them is far better than missing someone who does.
    - Each category has its own response with category-specific resources.
    - All responses include a general peer navigator offer.
    - The response tone is warm, non-judgmental, and action-oriented.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CRISIS KEYWORD PATTERNS
# ---------------------------------------------------------------------------
# Each category has a list of phrases. Matching is case-insensitive and
# checks for substring containment. Phrases are ordered roughly by
# specificity — longer phrases first to avoid false positives.

_SUICIDE_SELF_HARM_PHRASES = [
    # Direct statements
    "kill myself", "want to die", "wanna die", "wish i was dead",
    "wish i were dead", "better off dead", "end my life",
    "end it all", "take my life", "don't want to live",
    "dont want to live", "no reason to live", "nothing to live for",
    "can't go on", "cant go on", "not worth living",
    # Self-harm
    "hurt myself", "cutting myself", "harming myself", "self harm",
    "self-harm", "hurting myself",
    # Suicidal ideation
    "suicidal", "suicide", "overdose", "jump off",
    "hang myself", "slit my",
    # Passive / indirect hopelessness (P8)
    # These phrases don't mention death explicitly but signal suicidal ideation.
    # Erring on the side of false positives is correct here — showing crisis
    # resources to someone feeling hopeless does no harm.
    "what's the point anymore", "whats the point anymore",
    "what is the point anymore", "no point anymore",
    "nothing helps anymore", "nothing ever helps",
    "i give up", "given up on everything", "given up on life",
    "i can't do this anymore", "i cant do this anymore",
    "there's no hope", "theres no hope", "no hope left",
    "nobody cares", "no one cares if i",
    "would be better without me", "better off without me",
    "i'm done fighting", "im done fighting",
    "can't keep going", "cant keep going",
    "so tired of living", "tired of living like this",
]

_VIOLENCE_PHRASES = [
    # Threats to others
    "kill someone", "hurt someone", "want to hurt",
    "going to hurt", "gonna hurt",
    "kill him", "kill her", "kill them",
    "hurt him", "hurt her", "hurt them",
    # Weapons
    "have a gun", "have a knife", "got a weapon",
    "going to shoot", "gonna shoot",
]

_DOMESTIC_VIOLENCE_PHRASES = [
    # Abuse descriptions
    "being abused", "he hits me", "she hits me", "they hit me",
    "partner hits me", "husband hits me", "wife hits me",
    "boyfriend hits me", "girlfriend hits me",
    "being beaten", "beats me", "abusive relationship",
    "abusive partner", "domestic violence", "domestic abuse",
    "afraid of my partner", "scared of my partner",
    "afraid to go home", "scared to go home",
    "he hurts me", "she hurts me", "they hurt me",
    "partner hurts me", "violent partner",
    "stalking me", "being stalked", "restraining order",
    "order of protection",
    # Fleeing / implicit DV
    "he's going to come back", "she's going to come back",
    "going to come back", "coming back soon",
    "he's going to hurt me", "she's going to hurt me",
    "going to hurt me",
    "need to leave before", "have to leave before",
    "kicked me out", "threw me out", "locked me out",
]

# General safety concerns — not clearly DV or suicidal, but the person
# feels unsafe and needs immediate resources. Errs on the side of providing
# crisis resources rather than routine slot-filling.
_SAFETY_CONCERN_PHRASES = [
    "don't feel safe", "dont feel safe", "not safe here",
    "not safe where i am", "i'm not safe", "im not safe",
    "need to get out", "need to leave now", "have to get out",
    "can't stay here", "cant stay here",
    "in danger", "i'm in danger", "im in danger",
    "someone is threatening me", "being threatened",
    "someone is following me", "being followed",
    "need to get away",
    "afraid for my life", "fear for my life",
    "they're going to find me", "going to find me",
    # Youth runaway / unsafe home situations (P9)
    # Runaway youth face acute safety risks — prioritize crisis resources
    # alongside shelter search rather than treating as routine.
    "ran away from home", "run away from home", "running away from home",
    "ran away last night", "ran away yesterday",
    "i'm a runaway", "im a runaway", "i am a runaway",
    "kicked out of my home", "kicked out by my parents",
    "thrown out of my home", "parents kicked me out",
    "family kicked me out", "kicked out at",
    "unsafe at home", "home isn't safe", "home is not safe",
    "can't go home", "cant go home", "not safe to go home",
    "afraid to go home",
]

_TRAFFICKING_PHRASES = [
    # Labor trafficking
    "forced to work", "can't leave my job", "cant leave my job",
    "won't let me leave", "wont let me leave",
    "they took my passport", "took my documents",
    "locked in", "being held", "held against my will",
    "trapped", "can't escape", "cant escape",
    # Sex trafficking
    "forced into prostitution", "forced me into prostitution",
    "being trafficked", "being sex trafficked",
    "sex trafficking", "human trafficking",
    "making me do things", "pimped out",
    "they control me", "they won't let me go",
    "wont let me go", "prostitution",
]

_MEDICAL_EMERGENCY_PHRASES = [
    # Immediate danger
    "having a heart attack", "can't breathe", "cant breathe",
    "chest pain", "seizure", "stroke",
    "someone is dying", "bleeding out", "blood everywhere",
    "overdosing", "od'ing", "oding",
    "unconscious", "not breathing", "stopped breathing",
    "choking", "allergic reaction", "anaphylaxis",
]


# ---------------------------------------------------------------------------
# CRISIS RESPONSES
# ---------------------------------------------------------------------------
# Each response is warm, non-judgmental, and leads with the most
# relevant resource for that crisis type.

_SUICIDE_RESPONSE = (
    "I hear you, and I'm glad you reached out. What you're feeling matters, "
    "and there are people who want to help right now.\n\n"
    "Please reach out to one of these free, confidential resources:\n"
    "• 988 Suicide & Crisis Lifeline — call or text 988 (24/7)\n"
    "• Crisis Text Line — text HOME to 741741\n"
    "• Trevor Project (LGBTQ+ youth) — call 1-866-488-7386 or text START to 678-678\n\n"
    "You can also ask me to connect you with a peer navigator. "
    "You don't have to go through this alone."
)

_VIOLENCE_RESPONSE = (
    "If you or someone else is in immediate danger, please call 911.\n\n"
    "If you'd like to talk to someone:\n"
    "• 988 Suicide & Crisis Lifeline — call or text 988 (24/7)\n"
    "• Crisis Text Line — text HOME to 741741\n\n"
    "I can also connect you with a peer navigator who can help "
    "you find support services."
)

_DOMESTIC_VIOLENCE_RESPONSE = (
    "I'm sorry you're going through this. You deserve to be safe, "
    "and there is help available.\n\n"
    "• National Domestic Violence Hotline — 1-800-799-7233 (24/7) "
    "or text START to 88788\n"
    "• NYC Domestic Violence Hotline — 1-800-621-4673 (24/7, multilingual)\n"
    "• Safe Horizon — 1-800-621-HOPE (4673)\n\n"
    "If you're in immediate danger, please call 911.\n\n"
    "I can also help you find shelter or connect you with a peer navigator."
)

_TRAFFICKING_RESPONSE = (
    "What you're describing sounds very serious, and help is available. "
    "You are not in trouble.\n\n"
    "• National Human Trafficking Hotline — 1-888-373-7888 "
    "or text HELP to 233733 (BeFree)\n"
    "• If you're in immediate danger, call 911\n\n"
    "These services are confidential and available 24/7. "
    "I can also connect you with a peer navigator."
)

_MEDICAL_EMERGENCY_RESPONSE = (
    "If this is a medical emergency, please call 911 immediately.\n\n"
    "• Emergency: 911\n"
    "• Poison Control: 1-800-222-1222\n"
    "• NYC Health + Hospitals: call 311 for non-emergency medical help\n\n"
    "Once you're safe, I can help you find nearby clinics or health services."
)

_SAFETY_CONCERN_RESPONSE = (
    "Your safety comes first. If you're in immediate danger, please call 911.\n\n"
    "Here are resources that can help right now:\n"
    "• National Domestic Violence Hotline — 1-800-799-7233 (24/7) "
    "or text START to 88788\n"
    "• NYC Domestic Violence Hotline — 1-800-621-4673 (24/7, multilingual)\n"
    "• NYC Safe Horizons — 1-800-621-HOPE (4673)\n"
    "• 988 Suicide & Crisis Lifeline — call or text 988\n\n"
    "If you need shelter right away, I can help you find somewhere safe. "
    "Just let me know what area you're in."
)


# ---------------------------------------------------------------------------
# DETECTION
# ---------------------------------------------------------------------------

# Map category → (phrases, response)
_CRISIS_CATEGORIES = [
    ("suicide_self_harm", _SUICIDE_SELF_HARM_PHRASES, _SUICIDE_RESPONSE),
    ("medical_emergency", _MEDICAL_EMERGENCY_PHRASES, _MEDICAL_EMERGENCY_RESPONSE),
    ("domestic_violence", _DOMESTIC_VIOLENCE_PHRASES, _DOMESTIC_VIOLENCE_RESPONSE),
    ("safety_concern", _SAFETY_CONCERN_PHRASES, _SAFETY_CONCERN_RESPONSE),
    ("trafficking", _TRAFFICKING_PHRASES, _TRAFFICKING_RESPONSE),
    ("violence", _VIOLENCE_PHRASES, _VIOLENCE_RESPONSE),
]


def detect_crisis(text: str) -> Optional[Tuple[str, str]]:
    """
    Check if a message contains crisis language.

    Returns:
        (crisis_category, response_text) if crisis detected
        None if no crisis detected

    Categories: "suicide_self_harm", "medical_emergency",
                "domestic_violence", "trafficking", "violence"
    """
    lower = text.lower()

    for category, phrases, response in _CRISIS_CATEGORIES:
        for phrase in phrases:
            if phrase in lower:
                logger.warning(
                    f"Crisis detected: category='{category}', "
                    f"matched phrase='{phrase}'"
                )
                return (category, response)

    return None


def is_crisis(text: str) -> bool:
    """Quick check: does this message contain crisis language?"""
    return detect_crisis(text) is not None
