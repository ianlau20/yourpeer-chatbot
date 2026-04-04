# Copyright (c) 2024 Streetlives, Inc.
#
# Use of this source code is governed by an MIT-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/MIT.

"""
Claude LLM Client — shared Anthropic client for all LLM tasks.

Provides a single lazy-initialized Anthropic client and task-specific
helper functions. Replaces the previous Gemini client for conversational
responses while consolidating with the existing Claude usage for slot
extraction and crisis detection.

Model selection (from model analysis, April 2026):
    - Conversational responses: Haiku 4.5 (speed > reasoning depth)
    - Slot extraction: Haiku 4.5 (simple schema, bounded tool calling)
    - Crisis detection: Sonnet 4.6 (safety-critical, needs nuance)

See /admin/models in the staff console for the full cost/capability analysis.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MODELS — centralized so changes propagate everywhere
# ---------------------------------------------------------------------------

# Conversational fallback (warm, short replies, no tool calling)
CONVERSATIONAL_MODEL = "claude-haiku-4-5-20251001"

# Slot extraction (structured tool calling with simple schema)
SLOT_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

# Crisis detection (safety-critical classification, needs nuance)
CRISIS_DETECTION_MODEL = "claude-sonnet-4-6-20260217"

# ---------------------------------------------------------------------------
# CLIENT
# ---------------------------------------------------------------------------

try:
    import anthropic
    _anthropic_available = True
except ImportError:
    _anthropic_available = False
    logger.warning("anthropic SDK not installed — LLM features disabled")

_client = None
_init_error = None


def get_client():
    """Lazy-initialize a shared Anthropic client.

    Used by this module and can be imported by llm_slot_extractor.py and
    crisis_detector.py to avoid creating multiple client instances.
    """
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
            "ANTHROPIC_API_KEY not set. Add it to your .env file.\n"
            "Get a key at https://console.anthropic.com/"
        )
        raise _init_error

    try:
        _client = anthropic.Anthropic(api_key=api_key)
        logger.info(
            f"Anthropic client initialized. "
            f"Conversational: {CONVERSATIONAL_MODEL}, "
            f"Slots: {SLOT_EXTRACTION_MODEL}, "
            f"Crisis: {CRISIS_DETECTION_MODEL}"
        )
        return _client
    except Exception as e:
        _init_error = RuntimeError(f"Failed to initialize Anthropic client: {e}")
        raise _init_error


# ---------------------------------------------------------------------------
# CONVERSATIONAL REPLY (replaces gemini_reply)
# ---------------------------------------------------------------------------

def claude_reply(prompt: str) -> str:
    """Generate a short conversational reply using Claude Haiku.

    This replaces the previous gemini_reply() function. Used for general
    conversation when the user's message doesn't match service keywords
    or other classified intents.

    Returns empty string on failure so the caller can fall back to a
    safe static message.
    """
    try:
        client = get_client()
        response = client.messages.create(
            model=CONVERSATIONAL_MODEL,
            max_tokens=150,  # 1-3 sentences, never needs more
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text or ""
    except Exception as e:
        logger.error(f"Claude conversational reply failed: {e}")
        return "I'm having trouble connecting right now. Please try again."
