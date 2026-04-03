import os
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_model = None
_init_error = None


def _get_model():
    """Lazy-initialize the Gemini model on first use, not on import."""
    global _model, _init_error

    if _model is not None:
        return _model

    if _init_error is not None:
        raise _init_error

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL")

    if not gemini_api_key:
        _init_error = RuntimeError(
            "Missing GEMINI_API_KEY. Set it in your .env file. "
            "Get a free key at https://aistudio.google.com/apikey"
        )
        raise _init_error

    if not gemini_model:
        _init_error = RuntimeError(
            "Missing GEMINI_MODEL. Set it in your .env file. "
            'Example: GEMINI_MODEL="gemini-3-flash-preview"'
        )
        raise _init_error

    try:
        genai.configure(api_key=gemini_api_key)
        _model = genai.GenerativeModel(gemini_model)
        logger.info(f"Gemini model initialized: {gemini_model}")
        return _model
    except Exception as e:
        _init_error = RuntimeError(f"Failed to initialize Gemini: {e}")
        raise _init_error


def gemini_reply(prompt: str) -> str:
    """Generate a reply using Gemini. Returns empty string on failure."""
    try:
        model = _get_model()
        response = model.generate_content(prompt)
        return getattr(response, "text", "") or ""
    except Exception as e:
        logger.error(f"Gemini reply failed: {e}")
        return "I'm having trouble connecting right now. Please try again."
