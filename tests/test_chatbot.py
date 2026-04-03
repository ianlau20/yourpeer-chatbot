"""
Tests for the chatbot module — message classification, routing,
multi-turn session state, PII integration, and fallback behavior.

External dependencies (Gemini LLM, Streetlives DB) are mocked so
tests run without API keys or a database connection.

Run with: python -m pytest tests/test_chatbot.py -v
Or just:  python tests/test_chatbot.py
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.chatbot import (
    _classify_message,
    generate_reply,
    _no_results_message,
    _GREETING_RESPONSE,
    _RESET_RESPONSE,
    _THANKS_RESPONSE,
    _HELP_RESPONSE,
)
from app.services.session_store import clear_session, get_session_slots


# -----------------------------------------------------------------------
# MESSAGE CLASSIFICATION
# -----------------------------------------------------------------------

def test_classify_reset():
    """Reset phrases should classify as 'reset'."""
    phrases = ["start over", "reset", "nevermind", "cancel", "new search"]
    for phrase in phrases:
        assert _classify_message(phrase) == "reset", f"'{phrase}' should be reset"
    print("  PASS: reset classification")


def test_classify_greeting():
    """Short greetings should classify as 'greeting'."""
    phrases = ["hi", "hey", "hello", "yo", "good morning"]
    for phrase in phrases:
        assert _classify_message(phrase) == "greeting", f"'{phrase}' should be greeting"
    print("  PASS: greeting classification")


def test_classify_greeting_not_long_messages():
    """Long messages starting with 'hi' should NOT be greetings."""
    assert _classify_message("hi I need food in Brooklyn") != "greeting"
    assert _classify_message("hey can you find me a shelter in Queens") != "greeting"
    print("  PASS: long messages not classified as greeting")


def test_classify_thanks():
    """Thank-you phrases should classify as 'thanks'."""
    phrases = ["thanks", "thank you", "thx", "appreciate it", "that helps"]
    for phrase in phrases:
        assert _classify_message(phrase) == "thanks", f"'{phrase}' should be thanks"
    print("  PASS: thanks classification")


def test_classify_help():
    """Help phrases should classify as 'help'."""
    phrases = ["help", "what can you do", "how does this work", "who are you"]
    for phrase in phrases:
        assert _classify_message(phrase) == "help", f"'{phrase}' should be help"
    print("  PASS: help classification")


def test_classify_service():
    """Messages with service keywords should classify as 'service'."""
    phrases = [
        "I need food",
        "shelter in Brooklyn",
        "looking for a doctor",
        "I need a job",
    ]
    for phrase in phrases:
        assert _classify_message(phrase) == "service", f"'{phrase}' should be service"
    print("  PASS: service classification")


def test_classify_general():
    """Messages that don't match anything should classify as 'general'."""
    phrases = [
        "tell me more",
        "what about the second one",
        "ok",
        "sure",
        "I see",
    ]
    for phrase in phrases:
        assert _classify_message(phrase) == "general", f"'{phrase}' should be general"
    print("  PASS: general classification")


def test_classify_reset_takes_priority():
    """Reset should take priority over other categories."""
    # "start over" contains no service keywords but is a reset
    assert _classify_message("start over") == "reset"
    # "cancel" could be misread but should be reset
    assert _classify_message("cancel") == "reset"
    print("  PASS: reset takes priority")


def test_classify_with_punctuation():
    """Classification should work with punctuation."""
    assert _classify_message("hi!") == "greeting"
    assert _classify_message("thanks!!!") == "thanks"
    assert _classify_message("start over.") == "reset"
    assert _classify_message("help?") == "help"
    print("  PASS: punctuation handling")


# -----------------------------------------------------------------------
# GENERATE REPLY — ROUTING PATHS
# (mock Gemini and DB so tests run without external services)
# -----------------------------------------------------------------------

MOCK_QUERY_RESULTS = {
    "services": [
        {
            "service_name": "Test Food Pantry",
            "organization": "Test Org",
            "address": "123 Test St, Brooklyn, NY",
            "phone": "212-555-0001",
            "fees": "Free",
        }
    ],
    "result_count": 1,
    "template_used": "FoodQuery",
    "params_applied": {"taxonomy_name": "Food", "city": "Brooklyn"},
    "relaxed": False,
    "execution_ms": 50,
}

MOCK_EMPTY_RESULTS = {
    "services": [],
    "result_count": 0,
    "template_used": "FoodQuery",
    "params_applied": {"taxonomy_name": "Food", "city": "Brooklyn"},
    "relaxed": False,
    "execution_ms": 30,
}

MOCK_ERROR_RESULTS = {
    "services": [],
    "result_count": 0,
    "template_used": None,
    "params_applied": {},
    "relaxed": False,
    "execution_ms": 0,
    "error": "Unknown template: xyz",
}


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_greeting_route(mock_gemini, mock_query):
    """Greeting should return greeting response without querying DB."""
    result = generate_reply("hi", session_id="test-greeting")
    mock_query.assert_not_called()
    mock_gemini.assert_not_called()
    assert _GREETING_RESPONSE in result["response"]
    assert result["services"] == []
    print("  PASS: greeting route (no DB, no LLM)")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_greeting_with_existing_session(mock_gemini, mock_query):
    """Greeting with existing slots should acknowledge the session."""
    from app.services.session_store import save_session_slots
    save_session_slots("test-greeting-existing", {"service_type": "food"})

    result = generate_reply("hey", session_id="test-greeting-existing")
    assert "earlier search" in result["response"].lower() or "still have" in result["response"].lower()
    mock_query.assert_not_called()

    clear_session("test-greeting-existing")
    print("  PASS: greeting with existing session")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_reset_clears_session(mock_gemini, mock_query):
    """Reset should clear the session and return reset response."""
    from app.services.session_store import save_session_slots
    save_session_slots("test-reset", {"service_type": "food", "location": "Brooklyn"})

    result = generate_reply("start over", session_id="test-reset")
    assert result["slots"] == {}
    assert "fresh" in result["response"].lower() or "start" in result["response"].lower()
    mock_query.assert_not_called()

    # Verify session is actually cleared
    slots = get_session_slots("test-reset")
    assert slots == {}
    print("  PASS: reset clears session")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_thanks_route(mock_gemini, mock_query):
    """Thanks should return thanks response."""
    result = generate_reply("thank you", session_id="test-thanks")
    assert _THANKS_RESPONSE in result["response"]
    mock_query.assert_not_called()
    print("  PASS: thanks route")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_help_route(mock_gemini, mock_query):
    """Help should return help response."""
    result = generate_reply("what can you do", session_id="test-help")
    assert "free services" in result["response"].lower() or "find" in result["response"].lower()
    mock_query.assert_not_called()
    print("  PASS: help route")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_service_with_results(mock_gemini, mock_query):
    """Full service request should query DB and return service cards."""
    clear_session("test-service-results")
    result = generate_reply("I need food in Brooklyn", session_id="test-service-results")
    mock_query.assert_called_once()
    mock_gemini.assert_not_called()
    assert result["result_count"] == 1
    assert len(result["services"]) == 1
    assert result["services"][0]["service_name"] == "Test Food Pantry"
    assert "found" in result["response"].lower()

    clear_session("test-service-results")
    print("  PASS: service request with DB results")


@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_service_no_results(mock_gemini, mock_query):
    """Service request with no results should show helpful message."""
    clear_session("test-no-results")
    result = generate_reply("I need food in Brooklyn", session_id="test-no-results")
    mock_query.assert_called_once()
    assert result["result_count"] == 0
    assert "wasn't able to find" in result["response"] or "try" in result["response"].lower()

    clear_session("test-no-results")
    print("  PASS: service request with no results")


@patch("app.services.chatbot.query_services", side_effect=Exception("DB connection failed"))
@patch("app.services.chatbot.gemini_reply", return_value="Let me try to help another way.")
def test_db_failure_falls_back_to_gemini(mock_gemini, mock_query):
    """If DB query throws, should fall back to Gemini."""
    clear_session("test-db-fail")
    result = generate_reply("I need food in Brooklyn", session_id="test-db-fail")
    mock_query.assert_called_once()
    mock_gemini.assert_called_once()
    assert result["response"] == "Let me try to help another way."
    assert result["services"] == []

    clear_session("test-db-fail")
    print("  PASS: DB failure falls back to Gemini")


@patch("app.services.chatbot.query_services", side_effect=Exception("DB down"))
@patch("app.services.chatbot.gemini_reply", side_effect=Exception("Gemini down too"))
def test_both_db_and_gemini_fail(mock_gemini, mock_query):
    """If both DB and Gemini fail, should return safe static message."""
    clear_session("test-both-fail")
    result = generate_reply("I need food in Brooklyn", session_id="test-both-fail")
    assert "yourpeer.nyc" in result["response"].lower() or "trouble" in result["response"].lower()
    assert result["services"] == []

    clear_session("test-both-fail")
    print("  PASS: both DB + Gemini fail → safe static response")


@patch("app.services.chatbot.query_services", return_value=MOCK_ERROR_RESULTS)
@patch("app.services.chatbot.gemini_reply", return_value="I can try to help with that.")
def test_query_error_falls_back(mock_gemini, mock_query):
    """If query_services returns an error key, should fall back to Gemini."""
    clear_session("test-query-error")
    result = generate_reply("I need food in Brooklyn", session_id="test-query-error")
    mock_gemini.assert_called_once()
    assert result["response"] == "I can try to help with that."

    clear_session("test-query-error")
    print("  PASS: query error falls back to Gemini")


# -----------------------------------------------------------------------
# SERVICE FOLLOW-UP (not enough slots)
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_service_needs_followup(mock_gemini, mock_query):
    """Service keyword without location should ask follow-up, not query DB."""
    clear_session("test-followup")
    result = generate_reply("I need food", session_id="test-followup")
    mock_query.assert_not_called()
    assert result["follow_up_needed"] is True
    assert result["services"] == []
    assert "borough" in result["response"].lower() or "neighborhood" in result["response"].lower() or "area" in result["response"].lower()

    clear_session("test-followup")
    print("  PASS: partial slots trigger follow-up")


# -----------------------------------------------------------------------
# GENERAL CONVERSATION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply", return_value="I understand. How can I help you find what you need?")
def test_general_conversation(mock_gemini, mock_query):
    """Unrecognized messages should route to Gemini for conversational response."""
    clear_session("test-general")
    result = generate_reply("tell me more about that", session_id="test-general")
    mock_query.assert_not_called()
    mock_gemini.assert_called_once()
    assert result["response"] == "I understand. How can I help you find what you need?"

    clear_session("test-general")
    print("  PASS: general conversation routes to Gemini")


# -----------------------------------------------------------------------
# MULTI-TURN SESSION STATE
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_multi_turn_slot_accumulation(mock_gemini, mock_query):
    """Slots should accumulate across turns within the same session."""
    sid = "test-multi-turn"
    clear_session(sid)

    # Turn 1: service type only
    r1 = generate_reply("I need food", session_id=sid)
    assert r1["follow_up_needed"] is True
    assert r1["slots"].get("service_type") == "food"
    mock_query.assert_not_called()

    # Turn 2: location
    r2 = generate_reply("Brooklyn", session_id=sid)
    # Now it should have both slots and query the DB
    mock_query.assert_called_once()
    assert r2["slots"].get("service_type") == "food"
    assert "brooklyn" in r2["slots"].get("location", "").lower()

    clear_session(sid)
    print("  PASS: multi-turn slot accumulation")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_reset_then_new_search(mock_gemini, mock_query):
    """After reset, a new search should start from scratch."""
    sid = "test-reset-new"
    clear_session(sid)

    # Build up some slots
    generate_reply("I need food", session_id=sid)

    # Reset
    r_reset = generate_reply("start over", session_id=sid)
    assert r_reset["slots"] == {}

    # New search — should not carry over old slots
    r_new = generate_reply("shelter", session_id=sid)
    assert r_new["slots"].get("service_type") == "shelter"
    assert r_new["slots"].get("location") is None or "food" not in str(r_new["slots"])

    clear_session(sid)
    print("  PASS: reset then new search")


# -----------------------------------------------------------------------
# PII REDACTION IN CHATBOT FLOW
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_pii_redacted_in_transcript(mock_gemini, mock_query):
    """PII should be redacted in the stored transcript but slots should still extract."""
    sid = "test-pii-transcript"
    clear_session(sid)

    result = generate_reply(
        "My name is Sarah and I need food in Brooklyn",
        session_id=sid,
    )

    # Slots should extract correctly from the original message
    assert result["slots"].get("service_type") == "food"
    assert "brooklyn" in result["slots"].get("location", "").lower()

    # Transcript in session should have redacted version
    stored = get_session_slots(sid)
    transcript = stored.get("transcript", [])
    assert len(transcript) > 0
    last_msg = transcript[-1]["text"]
    assert "Sarah" not in last_msg
    assert "[NAME]" in last_msg
    # But location should survive in the redacted text
    assert "Brooklyn" in last_msg or "brooklyn" in last_msg

    clear_session(sid)
    print("  PASS: PII redacted in transcript, slots still extracted")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_phone_redacted_in_transcript(mock_gemini, mock_query):
    """Phone numbers should be redacted in transcript."""
    sid = "test-pii-phone"
    clear_session(sid)

    generate_reply("My number is 212-555-1234, I need food", session_id=sid)

    stored = get_session_slots(sid)
    transcript = stored.get("transcript", [])
    assert len(transcript) > 0
    last_msg = transcript[-1]["text"]
    assert "212-555-1234" not in last_msg
    assert "[PHONE]" in last_msg

    clear_session(sid)
    print("  PASS: phone redacted in transcript")


# -----------------------------------------------------------------------
# SESSION ID GENERATION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_session_id_generated_when_none(mock_gemini, mock_query):
    """If no session_id is provided, one should be generated."""
    result = generate_reply("hi")
    assert result["session_id"] is not None
    assert len(result["session_id"]) > 0
    # Clean up
    clear_session(result["session_id"])
    print("  PASS: session ID auto-generated")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_session_id_preserved(mock_gemini, mock_query):
    """If session_id is provided, it should be returned unchanged."""
    result = generate_reply("hi", session_id="my-custom-id")
    assert result["session_id"] == "my-custom-id"
    clear_session("my-custom-id")
    print("  PASS: session ID preserved")


# -----------------------------------------------------------------------
# RESPONSE STRUCTURE VALIDATION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_response_has_all_required_keys(mock_gemini, mock_query):
    """Every response should have all required keys for the ChatResponse model."""
    required_keys = [
        "session_id", "response", "follow_up_needed",
        "slots", "services", "result_count", "relaxed_search",
    ]

    # Test multiple routes
    for msg in ["hi", "I need food", "thank you", "start over", "help"]:
        result = generate_reply(msg, session_id=f"test-keys-{msg[:5]}")
        for key in required_keys:
            assert key in result, f"Missing key '{key}' in response for: {msg}"
        clear_session(f"test-keys-{msg[:5]}")

    print("  PASS: all response keys present")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_relaxed_search_flag(mock_gemini, mock_query):
    """relaxed_search should reflect whether the query was relaxed."""
    clear_session("test-relaxed")
    result = generate_reply("I need food in Brooklyn", session_id="test-relaxed")
    assert result["relaxed_search"] is False  # mock returns relaxed=False

    # Now test with relaxed=True
    mock_query.return_value = {
        **MOCK_QUERY_RESULTS,
        "relaxed": True,
    }
    clear_session("test-relaxed")
    result2 = generate_reply("I need food in Brooklyn", session_id="test-relaxed")
    assert result2["relaxed_search"] is True
    assert "broadened" in result2["response"].lower()

    clear_session("test-relaxed")
    print("  PASS: relaxed search flag")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nChatbot Tests\n" + "=" * 50)

    print("\n--- Message Classification ---")
    test_classify_reset()
    test_classify_greeting()
    test_classify_greeting_not_long_messages()
    test_classify_thanks()
    test_classify_help()
    test_classify_service()
    test_classify_general()
    test_classify_reset_takes_priority()
    test_classify_with_punctuation()

    print("\n--- Routing Paths ---")
    test_greeting_route()
    test_greeting_with_existing_session()
    test_reset_clears_session()
    test_thanks_route()
    test_help_route()
    test_service_with_results()
    test_service_no_results()
    test_service_needs_followup()
    test_general_conversation()

    print("\n--- Fallback Behavior ---")
    test_db_failure_falls_back_to_gemini()
    test_both_db_and_gemini_fail()
    test_query_error_falls_back()

    print("\n--- Multi-Turn Sessions ---")
    test_multi_turn_slot_accumulation()
    test_reset_then_new_search()

    print("\n--- PII in Chatbot Flow ---")
    test_pii_redacted_in_transcript()
    test_phone_redacted_in_transcript()

    print("\n--- Session ID ---")
    test_session_id_generated_when_none()
    test_session_id_preserved()

    print("\n--- Response Structure ---")
    test_response_has_all_required_keys()
    test_relaxed_search_flag()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
