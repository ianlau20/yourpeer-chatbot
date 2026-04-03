"""
Tests for the Gemini LLM client — lazy initialization, error caching,
API failure fallback, and successful reply path.

All external calls (google.genai) are mocked so tests run without
an API key or network access.

Run with: python -m pytest tests/test_gemini_client.py -v
Or just:  python tests/test_gemini_client.py
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# We need to reset the module-level globals before each test since
# _client, _init_error, and _model_name persist across calls.
import app.llm.gemini_client as gc


def _reset_globals():
    """Reset the module's lazy-init state between tests."""
    gc._client = None
    gc._init_error = None
    gc._model_name = None


# -----------------------------------------------------------------------
# LAZY INITIALIZATION
# -----------------------------------------------------------------------

@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "gemini-test"})
@patch("app.llm.gemini_client.genai")
def test_lazy_init_creates_client(mock_genai):
    """First call to _get_client should create the client."""
    _reset_globals()
    mock_genai.Client.return_value = MagicMock()

    client = gc._get_client()
    assert client is not None
    mock_genai.Client.assert_called_once_with(api_key="fake-key")
    assert gc._model_name == "gemini-test"
    print("  PASS: lazy init creates client")


@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "gemini-test"})
@patch("app.llm.gemini_client.genai")
def test_lazy_init_reuses_client(mock_genai):
    """Subsequent calls should reuse the cached client, not create a new one."""
    _reset_globals()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    client1 = gc._get_client()
    client2 = gc._get_client()

    assert client1 is client2
    mock_genai.Client.assert_called_once()  # only called once
    print("  PASS: lazy init reuses client")


# -----------------------------------------------------------------------
# MISSING ENV VARS
# -----------------------------------------------------------------------

@patch.dict(os.environ, {}, clear=True)
def test_missing_api_key_raises():
    """Missing GEMINI_API_KEY should raise RuntimeError."""
    _reset_globals()
    # Also clear any dotenv-loaded values
    with patch.dict(os.environ, {"GEMINI_MODEL": "test"}, clear=True):
        try:
            gc._get_client()
            assert False, "Should have raised RuntimeError"
        except RuntimeError as e:
            assert "GEMINI_API_KEY" in str(e)
    print("  PASS: missing API key raises")


@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}, clear=True)
def test_missing_model_raises():
    """Missing GEMINI_MODEL should raise RuntimeError."""
    _reset_globals()
    try:
        gc._get_client()
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "GEMINI_MODEL" in str(e)
    print("  PASS: missing model raises")


# -----------------------------------------------------------------------
# ERROR CACHING
# -----------------------------------------------------------------------

@patch.dict(os.environ, {}, clear=True)
def test_init_error_cached():
    """Once init fails, subsequent calls should raise immediately
    without retrying the initialization."""
    _reset_globals()
    with patch.dict(os.environ, {"GEMINI_MODEL": "test"}, clear=True):
        # First call — fails and caches the error
        try:
            gc._get_client()
        except RuntimeError:
            pass

        assert gc._init_error is not None

        # Second call — should raise the SAME cached error immediately
        try:
            gc._get_client()
            assert False, "Should have raised cached error"
        except RuntimeError as e:
            assert "GEMINI_API_KEY" in str(e)
    print("  PASS: init error is cached")


@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "test"})
@patch("app.llm.gemini_client.genai")
def test_client_creation_failure_cached(mock_genai):
    """If genai.Client() throws, the error should be cached."""
    _reset_globals()
    mock_genai.Client.side_effect = Exception("Network error")

    try:
        gc._get_client()
    except RuntimeError as e:
        assert "Failed to initialize" in str(e)

    # Second call should raise cached error without calling Client again
    mock_genai.Client.reset_mock()
    try:
        gc._get_client()
    except RuntimeError:
        pass
    mock_genai.Client.assert_not_called()
    print("  PASS: client creation failure cached")


# -----------------------------------------------------------------------
# GEMINI_REPLY — SUCCESS
# -----------------------------------------------------------------------

@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "gemini-test"})
@patch("app.llm.gemini_client.genai")
def test_gemini_reply_success(mock_genai):
    """Successful API call should return the response text."""
    _reset_globals()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = "Here are some food options."
    mock_client.models.generate_content.return_value = mock_response

    result = gc.gemini_reply("Find food in Brooklyn")

    assert result == "Here are some food options."
    mock_client.models.generate_content.assert_called_once_with(
        model="gemini-test",
        contents="Find food in Brooklyn",
    )
    print("  PASS: gemini_reply success")


@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "gemini-test"})
@patch("app.llm.gemini_client.genai")
def test_gemini_reply_empty_text(mock_genai):
    """If response.text is None, should return empty string."""
    _reset_globals()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client

    mock_response = MagicMock()
    mock_response.text = None
    mock_client.models.generate_content.return_value = mock_response

    result = gc.gemini_reply("test")
    assert result == ""
    print("  PASS: gemini_reply with None text returns empty string")


# -----------------------------------------------------------------------
# GEMINI_REPLY — FAILURE
# -----------------------------------------------------------------------

@patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key", "GEMINI_MODEL": "gemini-test"})
@patch("app.llm.gemini_client.genai")
def test_gemini_reply_api_failure(mock_genai):
    """API call failure should return the fallback string, not crash."""
    _reset_globals()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client
    mock_client.models.generate_content.side_effect = Exception("API timeout")

    result = gc.gemini_reply("test prompt")

    assert "trouble connecting" in result.lower()
    assert "try again" in result.lower()
    print("  PASS: gemini_reply API failure returns fallback")


def test_gemini_reply_init_failure():
    """If client init fails, gemini_reply should return fallback, not raise."""
    _reset_globals()
    # Force init to fail by clearing env vars
    with patch.dict(os.environ, {}, clear=True):
        result = gc.gemini_reply("test")
        assert "trouble connecting" in result.lower()
    print("  PASS: gemini_reply init failure returns fallback")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nGemini Client Tests\n" + "=" * 50)

    print("\n--- Lazy Initialization ---")
    test_lazy_init_creates_client()
    test_lazy_init_reuses_client()

    print("\n--- Missing Env Vars ---")
    test_missing_api_key_raises()
    test_missing_model_raises()

    print("\n--- Error Caching ---")
    test_init_error_cached()
    test_client_creation_failure_cached()

    print("\n--- Reply Success ---")
    test_gemini_reply_success()
    test_gemini_reply_empty_text()

    print("\n--- Reply Failure ---")
    test_gemini_reply_api_failure()
    test_gemini_reply_init_failure()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
