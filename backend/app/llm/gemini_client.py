import os
import logging
from dotenv import load_dotenv
from google import genai

load_dotenv()
logger = logging.getLogger(__name__)

_client = None
_init_error = None
_model_name = None


def _get_client():
    """Lazy-initialize the Gemini client on first use, not on import."""
    global _client, _init_error, _model_name

    if _client is not None:
        return _client

    if _init_error is not None:
        raise _init_error

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    _model_name = os.getenv("GEMINI_MODEL")

    if not gemini_api_key:
        _init_error = RuntimeError(
            "Missing GEMINI_API_KEY. Set it in your .env file. "
            "Get a free key at https://aistudio.google.com/apikey"
        )
        raise _init_error

    if not _model_name:
        _init_error = RuntimeError(
            "Missing GEMINI_MODEL. Set it in your .env file. "
            'Example: GEMINI_MODEL="gemini-2.0-flash"'
        )
        raise _init_error

    try:
        _client = genai.Client(api_key=gemini_api_key)
        logger.info(f"Gemini client initialized, model: {_model_name}")
        return _client
    except Exception as e:
        _init_error = RuntimeError(f"Failed to initialize Gemini: {e}")
        raise _init_error


def gemini_reply(prompt: str) -> str:
    """Generate a reply using Gemini. Returns empty string on failure."""
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_model_name,
            contents=prompt,
        )
        return response.text or ""
    except Exception as e:
        logger.error(f"Gemini reply failed: {e}")
        return "I'm having trouble connecting right now. Please try again."
