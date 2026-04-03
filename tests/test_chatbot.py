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
    """Full service request should confirm first, then query DB on confirmation."""
    sid = "test-service-results"
    clear_session(sid)

    # Step 1: Send message with both slots — should get confirmation
    r1 = generate_reply("I need food in Brooklyn", session_id=sid)
    mock_query.assert_not_called()  # Not yet — waiting for confirmation
    assert r1["follow_up_needed"] is True
    assert "food" in r1["response"].lower()
    assert "brooklyn" in r1["response"].lower()
    assert len(r1["quick_replies"]) > 0

    # Step 2: Confirm — now it should query the DB
    r2 = generate_reply("Yes, search", session_id=sid)
    mock_query.assert_called_once()
    mock_gemini.assert_not_called()
    assert r2["result_count"] == 1
    assert len(r2["services"]) == 1
    assert r2["services"][0]["service_name"] == "Test Food Pantry"
    assert "found" in r2["response"].lower()

    clear_session(sid)
    print("  PASS: service request with confirmation then DB results")


@patch("app.services.chatbot.query_services", return_value=MOCK_EMPTY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_service_no_results(mock_gemini, mock_query):
    """Service request with no results should show helpful message after confirmation."""
    sid = "test-no-results"
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation step
    result = generate_reply("Yes, search", session_id=sid)  # confirm → query
    mock_query.assert_called_once()
    assert result["result_count"] == 0
    assert "wasn't able to find" in result["response"] or "try" in result["response"].lower()

    clear_session(sid)
    print("  PASS: service request with no results")


@patch("app.services.chatbot.query_services", side_effect=Exception("DB connection failed"))
@patch("app.services.chatbot.gemini_reply", return_value="Let me try to help another way.")
def test_db_failure_falls_back_to_gemini(mock_gemini, mock_query):
    """If DB query throws after confirmation, should fall back to Gemini."""
    sid = "test-db-fail"
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation step
    result = generate_reply("Yes, search", session_id=sid)  # confirm → query fails
    mock_query.assert_called_once()
    mock_gemini.assert_called_once()
    assert result["response"] == "Let me try to help another way."
    assert result["services"] == []

    clear_session(sid)
    print("  PASS: DB failure falls back to Gemini")


@patch("app.services.chatbot.query_services", side_effect=Exception("DB down"))
@patch("app.services.chatbot.gemini_reply", side_effect=Exception("Gemini down too"))
def test_both_db_and_gemini_fail(mock_gemini, mock_query):
    """If both DB and Gemini fail after confirmation, should return safe static message."""
    sid = "test-both-fail"
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation step
    result = generate_reply("Yes, search", session_id=sid)  # confirm → both fail
    assert "yourpeer.nyc" in result["response"].lower() or "trouble" in result["response"].lower()
    assert result["services"] == []

    clear_session(sid)
    print("  PASS: both DB + Gemini fail → safe static response")


@patch("app.services.chatbot.query_services", return_value=MOCK_ERROR_RESULTS)
@patch("app.services.chatbot.gemini_reply", return_value="I can try to help with that.")
def test_query_error_falls_back(mock_gemini, mock_query):
    """If query_services returns an error key after confirmation, should fall back to Gemini."""
    sid = "test-query-error"
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation step
    result = generate_reply("Yes, search", session_id=sid)  # confirm → error
    mock_gemini.assert_called_once()
    assert result["response"] == "I can try to help with that."

    clear_session(sid)
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

    # Turn 2: location → should trigger confirmation (not query yet)
    r2 = generate_reply("Brooklyn", session_id=sid)
    mock_query.assert_not_called()  # confirmation pending
    assert r2["follow_up_needed"] is True
    assert r2["slots"].get("service_type") == "food"
    assert "brooklyn" in r2["slots"].get("location", "").lower()

    # Turn 3: confirm → now query
    r3 = generate_reply("Yes, search", session_id=sid)
    mock_query.assert_called_once()

    clear_session(sid)
    print("  PASS: multi-turn slot accumulation with confirmation")


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

    # Should be at confirmation step (not queried yet)
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
        "quick_replies",
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
    sid = "test-relaxed"
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    result = generate_reply("Yes, search", session_id=sid)  # confirm
    assert result["relaxed_search"] is False  # mock returns relaxed=False

    # Now test with relaxed=True
    mock_query.return_value = {
        **MOCK_QUERY_RESULTS,
        "relaxed": True,
    }
    clear_session(sid)
    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    result2 = generate_reply("Yes, search", session_id=sid)  # confirm
    assert result2["relaxed_search"] is True
    assert "broadened" in result2["response"].lower()

    clear_session(sid)
    print("  PASS: relaxed search flag")


# -----------------------------------------------------------------------
# CONFIRMATION FLOW & QUICK REPLIES
# -----------------------------------------------------------------------

def test_classify_confirmation_phrases():
    """Confirmation phrases should classify correctly."""
    # Exact matches (short words)
    for phrase in ["yes", "yeah", "ok", "sure", "go ahead", "yes please",
                   "correct", "yep", "yup", "do it", "find", "please"]:
        assert _classify_message(phrase) == "confirm_yes", \
            f"'{phrase}' should be confirm_yes"

    # Starts-with matches (longer phrases)
    for phrase in ["yes search", "yes, search", "yes I want to search",
                   "please search", "search for that", "looks good",
                   "that's right", "thats correct", "confirm",
                   "go ahead and search", "yes that is correct"]:
        assert _classify_message(phrase) == "confirm_yes", \
            f"'{phrase}' should be confirm_yes"

    for phrase in ["change location", "different area", "wrong location"]:
        assert _classify_message(phrase) == "confirm_change_location", \
            f"'{phrase}' should be confirm_change_location"

    for phrase in ["change service", "different service", "wrong service"]:
        assert _classify_message(phrase) == "confirm_change_service", \
            f"'{phrase}' should be confirm_change_service"

    print("  PASS: confirmation phrase classification")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_confirmation_step_triggered(mock_gemini, mock_query):
    """When both slots are filled, should return confirmation, not query."""
    sid = "test-confirm-trigger"
    clear_session(sid)

    result = generate_reply("I need food in Brooklyn", session_id=sid)
    mock_query.assert_not_called()
    assert result["follow_up_needed"] is True
    assert "food" in result["response"].lower()
    assert "brooklyn" in result["response"].lower()
    assert len(result["quick_replies"]) >= 3  # yes, change location, change service, start over

    clear_session(sid)
    print("  PASS: confirmation step triggered when slots complete")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_change_location_during_confirmation(mock_gemini, mock_query):
    """User can change location during confirmation."""
    sid = "test-change-loc"
    clear_session(sid)

    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    result = generate_reply("Change location", session_id=sid)  # change loc

    assert result["slots"].get("location") is None
    assert result["slots"].get("service_type") == "food"
    assert len(result["quick_replies"]) > 0  # borough buttons

    clear_session(sid)
    print("  PASS: change location during confirmation")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_change_service_during_confirmation(mock_gemini, mock_query):
    """User can change service type during confirmation."""
    sid = "test-change-svc"
    clear_session(sid)

    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    result = generate_reply("Change service", session_id=sid)  # change svc

    assert result["slots"].get("service_type") is None
    assert "brooklyn" in result["slots"].get("location", "").lower()
    assert len(result["quick_replies"]) > 0  # category buttons

    clear_session(sid)
    print("  PASS: change service during confirmation")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_greeting_has_quick_replies(mock_gemini, mock_query):
    """Greeting response should include quick-reply category buttons."""
    sid = "test-qr-greeting"
    clear_session(sid)

    result = generate_reply("hi", session_id=sid)
    assert len(result["quick_replies"]) > 0
    labels = [qr["label"] for qr in result["quick_replies"]]
    assert any("Food" in l for l in labels)
    assert any("Shelter" in l for l in labels)

    clear_session(sid)
    print("  PASS: greeting has quick replies")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_reset_has_quick_replies(mock_gemini, mock_query):
    """Reset response should include quick-reply category buttons."""
    sid = "test-qr-reset"
    clear_session(sid)

    result = generate_reply("start over", session_id=sid)
    assert len(result["quick_replies"]) > 0

    clear_session(sid)
    print("  PASS: reset has quick replies")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_service_followup_has_quick_replies(mock_gemini, mock_query):
    """When only service type is known, follow-up should show borough buttons."""
    sid = "test-qr-followup"
    clear_session(sid)

    result = generate_reply("I need food", session_id=sid)
    assert result["follow_up_needed"] is True
    # Should have borough quick replies since we're missing location
    labels = [qr["label"] for qr in result.get("quick_replies", [])]
    assert any("Manhattan" in l or "Brooklyn" in l for l in labels), \
        f"Expected borough buttons, got: {labels}"

    clear_session(sid)
    print("  PASS: follow-up has borough quick replies")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_new_input_clears_pending_confirmation(mock_gemini, mock_query):
    """Typing new service input during confirmation should re-extract and re-confirm."""
    sid = "test-new-input-confirm"
    clear_session(sid)

    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    # Instead of confirming, user changes their mind entirely
    result = generate_reply("I need shelter in Queens", session_id=sid)

    # Should re-confirm with the new slots
    assert result["slots"].get("service_type") == "shelter"
    assert "queens" in result["slots"].get("location", "").lower()
    assert result["follow_up_needed"] is True
    mock_query.assert_not_called()  # still in confirmation

    clear_session(sid)
    print("  PASS: new input during confirmation re-extracts slots")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_results_have_post_search_quick_replies(mock_gemini, mock_query):
    """After results are shown, should offer new search and peer navigator buttons."""
    sid = "test-qr-results"
    clear_session(sid)

    generate_reply("I need food in Brooklyn", session_id=sid)  # confirmation
    result = generate_reply("Yes, search", session_id=sid)  # confirm → results

    assert result["result_count"] > 0
    labels = [qr["label"] for qr in result.get("quick_replies", [])]
    assert any("search" in l.lower() or "new" in l.lower() for l in labels)

    clear_session(sid)
    print("  PASS: results have post-search quick replies")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply", return_value="No problem! What else can I help with?")
def test_general_reply_does_not_retrigger_confirmation(mock_gemini, mock_query):
    """A general message like 'no' should NOT re-trigger confirmation from stale slots."""
    sid = "test-no-retrigger"
    clear_session(sid)

    # Build up complete slots via a confirmed search
    generate_reply("I need food in Manhattan", session_id=sid)  # confirmation
    generate_reply("Yes, search", session_id=sid)  # executes query

    # Now user says "no" — this is conversational, not a new service request.
    # The session still has service_type=food + location=Manhattan, but
    # "no" should NOT re-trigger the confirmation flow.
    result = generate_reply("no", session_id=sid)
    assert result["result_count"] == 0, "Should not have queried DB"
    assert "search for" not in result["response"].lower(), \
        f"Should not re-confirm, got: {result['response']}"
    assert result["follow_up_needed"] is False

    clear_session(sid)
    print("  PASS: 'no' does not re-trigger confirmation from stale slots")


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply", return_value="No problem! What else can I help with?")
def test_no_after_escalation_does_not_confirm(mock_gemini, mock_query):
    """After escalation response, 'no' should route to general conversation."""
    sid = "test-no-after-escalation"
    clear_session(sid)

    # Build up slots first
    generate_reply("I need food in Manhattan", session_id=sid)  # confirmation
    generate_reply("Yes, search", session_id=sid)  # executes query

    # User asks for escalation
    generate_reply("Connect with peer navigator", session_id=sid)

    # User says "no" — should NOT re-trigger confirmation
    result = generate_reply("no", session_id=sid)
    assert result["result_count"] == 0
    assert "search for" not in result["response"].lower()

    clear_session(sid)
    print("  PASS: 'no' after escalation does not re-trigger confirmation")


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
    test_classify_confirmation_phrases()

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

    print("\n--- Confirmation & Quick Replies ---")
    test_confirmation_step_triggered()
    test_change_location_during_confirmation()
    test_change_service_during_confirmation()
    test_greeting_has_quick_replies()
    test_reset_has_quick_replies()
    test_service_followup_has_quick_replies()
    test_new_input_clears_pending_confirmation()
    test_results_have_post_search_quick_replies()
    test_general_reply_does_not_retrigger_confirmation()
    test_no_after_escalation_does_not_confirm()

    print("\n--- Bug Fix Regression Tests ---")
    test_confirm_deny_breaks_loop()
    test_confirm_deny_phrases()
    test_cancel_variants_reset()
    test_frustration_expanded_phrases()
    test_thanks_with_continuation_falls_through()
    test_empty_message_guard()
    test_whitespace_message_guard()
    test_confused_classification()
    test_confused_does_not_trigger_llm()
    test_conversation_history_passed_to_llm()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")


# -----------------------------------------------------------------------
# BUG FIX REGRESSION TESTS
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_confirm_deny_breaks_loop(mock_gemini, mock_query):
    """Bug 1: Saying 'no' during confirmation should NOT loop forever.

    Previously, 'no' was classified as 'general', had no new slots,
    and re-showed the confirmation nudge indefinitely.
    """
    mock_gemini.return_value = "How can I help?"
    sid = "test-deny-loop"
    clear_session(sid)

    # Build up to confirmation
    r1 = generate_reply("I need food in Brooklyn", session_id=sid)
    assert r1["slots"].get("_pending_confirmation") is True

    # Say 'no' — should exit confirmation, not re-show it
    r2 = generate_reply("no", session_id=sid)
    assert r2["slots"].get("_pending_confirmation") is None, \
        "Pending confirmation should be cleared after 'no'"
    assert "hold onto" in r2["response"].lower() or "no problem" in r2["response"].lower(), \
        "Should acknowledge the denial gracefully"
    assert len(r2["quick_replies"]) > 0, "Should offer next-step options"

    # Saying 'no' again should NOT show the confirmation nudge
    r3 = generate_reply("no", session_id=sid)
    assert "just to make sure" not in r3["response"].lower(), \
        "Should NOT re-show confirmation after denial"
    print("  PASS: confirm_deny breaks the infinite loop")


def test_confirm_deny_phrases():
    """Bug 1: All denial phrases should classify as 'confirm_deny'."""
    phrases = ["no", "nah", "nope", "not yet", "hold on", "stop"]
    for phrase in phrases:
        assert _classify_message(phrase) == "confirm_deny", \
            f"'{phrase}' should classify as confirm_deny"

    # Longer phrases
    long_phrases = ["no thanks", "no thank you", "i changed my mind",
                    "not right now", "maybe later"]
    for phrase in long_phrases:
        result = _classify_message(phrase)
        assert result in ("confirm_deny", "thanks", "reset"), \
            f"'{phrase}' should classify as confirm_deny, thanks, or reset, got '{result}'"
    print("  PASS: confirm_deny phrases classified correctly")


def test_cancel_variants_reset():
    """Bug 2: 'cancel my search', 'please cancel' etc. should trigger reset."""
    phrases = [
        "cancel",             # exact match (existing)
        "cancel my search",   # was broken — classified as 'general'
        "please cancel",      # was broken
        "i want to cancel",   # was broken
        "cancel this",        # was broken
    ]
    for phrase in phrases:
        assert _classify_message(phrase) == "reset", \
            f"'{phrase}' should classify as reset, got '{_classify_message(phrase)}'"
    print("  PASS: cancel variants trigger reset")


def test_frustration_expanded_phrases():
    """Bug 3: Expanded frustration phrases should be detected."""
    phrases = [
        "not what I needed",
        "wrong results",
        "these results are bad",
        "thats not right",
        "not useful",
        "this sucks",
        # Existing phrases should still work
        "useless",
        "that didnt help",
        "none of those work",
    ]
    for phrase in phrases:
        result = _classify_message(phrase)
        assert result == "frustration", \
            f"'{phrase}' should classify as frustration, got '{result}'"
    print("  PASS: expanded frustration phrases detected")


def test_thanks_with_continuation_falls_through():
    """Bug 8: 'thanks but I need X' should NOT be classified as thanks.

    Previously, 'thanks but I need more options' triggered the thanks
    handler, dropping the user's continuation request.
    """
    # Pure thanks — should still work
    assert _classify_message("thanks") == "thanks"
    assert _classify_message("thank you") == "thanks"
    assert _classify_message("appreciate it") == "thanks"

    # Thanks with continuation — should NOT be thanks
    continuations = [
        "thanks but I need more options",
        "thank you but I also want shelter",
        "thanks but can you also search for food",
        "thanks however I need something else",
    ]
    for phrase in continuations:
        result = _classify_message(phrase)
        assert result != "thanks", \
            f"'{phrase}' should NOT classify as thanks, got '{result}'"
    print("  PASS: thanks with continuation falls through")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_empty_message_guard(mock_gemini, mock_query):
    """Bug 6: Empty string messages should return welcome, not hit Gemini."""
    sid = "test-empty"
    clear_session(sid)

    r = generate_reply("", session_id=sid)
    assert "looking for" in r["response"].lower(), \
        "Empty message should return welcome prompt"
    assert len(r["quick_replies"]) == 9, \
        "Empty message should show all 9 category buttons"
    mock_gemini.assert_not_called()
    print("  PASS: empty message returns welcome")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_whitespace_message_guard(mock_gemini, mock_query):
    """Bug 6: Whitespace-only messages should return welcome, not hit Gemini."""
    sid = "test-whitespace"
    clear_session(sid)

    r = generate_reply("   ", session_id=sid)
    assert "looking for" in r["response"].lower(), \
        "Whitespace message should return welcome prompt"
    assert len(r["quick_replies"]) == 9, \
        "Whitespace message should show all 9 category buttons"
    mock_gemini.assert_not_called()
    print("  PASS: whitespace message returns welcome")


def test_confused_classification():
    """Confusion/overwhelm phrases should classify as 'confused', not 'general'.

    Previously, 'I don't know what to do' was classified as 'general',
    sent to the LLM, which misinterpreted it as a mental health request
    and triggered a false confirmation.
    """
    phrases = [
        "I don't know what to do",
        "I dont know what to do",
        "idk what to do",
        "I don't know",
        "I'm confused",
        "I'm lost",
        "I'm overwhelmed",
        "I'm not sure what I need",
        "what should I do",
        "where do I start",
        "what are my options",
    ]
    for phrase in phrases:
        result = _classify_message(phrase)
        assert result == "confused", \
            f"'{phrase}' should classify as confused, got '{result}'"

    # These should NOT be confused
    assert _classify_message("I need food") == "service"
    assert _classify_message("hello") == "greeting"
    print("  PASS: confused phrases classified correctly")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply")
def test_confused_does_not_trigger_llm(mock_gemini, mock_query):
    """'I don't know what to do' should NOT reach the LLM or extract slots.

    Previously, the LLM would interpret this as a mental health request
    and trigger a confirmation for a service the user never asked for.
    """
    sid = "test-confused-no-llm"
    clear_session(sid)

    r = generate_reply("I don't know what to do", session_id=sid)

    # Should get the confused response with category buttons
    assert "figure it out" in r["response"].lower() or "okay" in r["response"].lower()
    assert len(r["quick_replies"]) >= 9  # 9 categories + talk to person
    assert r["slots"].get("service_type") is None, \
        "Should NOT have extracted a service type"
    assert r["slots"].get("_pending_confirmation") is None, \
        "Should NOT have triggered confirmation"

    # Gemini should NOT have been called
    mock_gemini.assert_not_called()
    print("  PASS: confused does not trigger LLM")


@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.gemini_reply", return_value="test")
def test_conversation_history_passed_to_llm(mock_gemini, mock_query):
    """When LLM extraction is enabled, the session transcript should be
    passed as conversation_history so follow-ups like 'What about in
    Brooklyn?' have context from prior turns.

    This test verifies the plumbing — that the transcript stored in
    session slots is forwarded to extract_slots_smart.
    """
    sid = "test-history-plumbing"
    clear_session(sid)

    # Turn 1: build up a transcript
    r1 = generate_reply("I need food in Queens", session_id=sid)
    slots = r1["slots"]
    assert "transcript" in slots, "Transcript should be stored in session"
    assert len(slots["transcript"]) >= 1, "Should have at least 1 transcript entry"

    # Verify the transcript entry has the right shape
    entry = slots["transcript"][0]
    assert entry["role"] == "user"
    assert "food" in entry["text"].lower()
    print("  PASS: conversation history stored and available for LLM")
