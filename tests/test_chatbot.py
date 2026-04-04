"""
Tests for the chatbot module — message classification, routing,
multi-turn session state, PII integration, and fallback behavior.

External dependencies (Claude LLM, Streetlives DB) are mocked so
tests run without API keys or a database connection.

Run: pytest tests/test_chatbot.py
"""

from unittest.mock import patch, MagicMock

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
from conftest import (
    MOCK_QUERY_RESULTS, MOCK_EMPTY_RESULTS,
    send, send_multi, assert_classified,
)


# -----------------------------------------------------------------------
# MESSAGE CLASSIFICATION
# -----------------------------------------------------------------------

def test_classify_reset():
    """Reset phrases should classify as 'reset'."""
    for phrase in ["start over", "reset", "nevermind", "cancel", "new search"]:
        assert_classified(phrase, "reset")


def test_classify_greeting():
    """Short greetings should classify as 'greeting'."""
    for phrase in ["hi", "hey", "hello", "yo", "good morning"]:
        assert_classified(phrase, "greeting")


def test_classify_greeting_not_long_messages():
    """Long messages starting with 'hi' should NOT be greetings."""
    assert _classify_message("hi I need food in Brooklyn") != "greeting"
    assert _classify_message("hey can you find me a shelter in Queens") != "greeting"


def test_classify_thanks():
    """Thank-you phrases should classify as 'thanks'."""
    for phrase in ["thanks", "thank you", "thx", "appreciate it", "that helps"]:
        assert_classified(phrase, "thanks")


def test_classify_help():
    """Help phrases should classify as 'help'."""
    for phrase in ["help", "what can you do", "how does this work", "who are you"]:
        assert_classified(phrase, "help")


def test_classify_service():
    """Messages with service keywords should classify as 'service'."""
    for phrase in ["I need food", "shelter in Brooklyn",
                   "looking for a doctor", "I need a job"]:
        assert_classified(phrase, "service")


def test_classify_general():
    """Messages that don't match anything should classify as 'general'."""
    for phrase in ["tell me more", "what about the second one", "I see"]:
        assert_classified(phrase, "general")


def test_classify_reset_takes_priority():
    """Reset should take priority over other categories."""
    assert_classified("start over", "reset")
    assert_classified("cancel", "reset")


def test_classify_with_punctuation():
    """Classification should work with punctuation."""
    assert_classified("hi!", "greeting")
    assert_classified("thanks!!!", "thanks")
    assert_classified("start over.", "reset")
    assert_classified("help?", "help")


# -----------------------------------------------------------------------
# GENERATE REPLY — ROUTING PATHS
# -----------------------------------------------------------------------

MOCK_ERROR_RESULTS = {
    "services": [],
    "result_count": 0,
    "template_used": None,
    "params_applied": {},
    "relaxed": False,
    "execution_ms": 0,
    "error": "Unknown template: xyz",
}


def test_greeting_route(fresh_session):
    """Greeting should return greeting response without querying DB."""
    result = send("hi", session_id=fresh_session)
    assert _GREETING_RESPONSE in result["response"]
    assert result["services"] == []


def test_greeting_with_existing_session(fresh_session):
    """Greeting with existing slots should acknowledge the session."""
    from app.services.session_store import save_session_slots
    save_session_slots(fresh_session, {"service_type": "food"})

    result = send("hey", session_id=fresh_session)
    assert "earlier search" in result["response"].lower() or "still have" in result["response"].lower()


def test_reset_clears_session(fresh_session):
    """Reset should clear the session and return reset response."""
    from app.services.session_store import save_session_slots
    save_session_slots(fresh_session, {"service_type": "food", "location": "Brooklyn"})

    result = send("start over", session_id=fresh_session)
    assert result["slots"] == {}
    assert "fresh" in result["response"].lower() or "start" in result["response"].lower()
    assert get_session_slots(fresh_session) == {}


def test_thanks_route(fresh_session):
    """Thanks should return thanks response."""
    result = send("thank you", session_id=fresh_session)
    assert _THANKS_RESPONSE in result["response"]


def test_help_route(fresh_session):
    """Help should return help response."""
    result = send("what can you do", session_id=fresh_session)
    assert "free services" in result["response"].lower() or "find" in result["response"].lower()


def test_service_with_results(fresh_session):
    """Full service request should confirm first, then query DB on confirmation."""
    r1, r2 = send_multi(
        ["I need food in Brooklyn", "Yes, search"],
        session_id=fresh_session,
    )
    assert r1["follow_up_needed"] is True
    assert "food" in r1["response"].lower()
    assert "brooklyn" in r1["response"].lower()
    assert r2["result_count"] == 1
    assert r2["services"][0]["service_name"] == "Test Food Pantry"


def test_service_no_results(fresh_session):
    """Service request with no results should show helpful message after confirmation."""
    results = send_multi(
        ["I need food in Brooklyn", "Yes, search"],
        session_id=fresh_session,
        mock_query_return=MOCK_EMPTY_RESULTS,
    )
    assert results[-1]["result_count"] == 0
    assert "wasn't able to find" in results[-1]["response"] or "try" in results[-1]["response"].lower()


@patch("app.services.chatbot.query_services", side_effect=Exception("DB connection failed"))
@patch("app.services.chatbot.claude_reply", return_value="Let me try to help another way.")
def test_db_failure_falls_back_to_claude(mock_claude, mock_query, fresh_session):
    """If DB query throws after confirmation, should fall back to Claude."""
    generate_reply("I need food in Brooklyn", session_id=fresh_session)
    result = generate_reply("Yes, search", session_id=fresh_session)
    mock_query.assert_called_once()
    mock_claude.assert_called_once()
    assert result["response"] == "Let me try to help another way."
    assert result["services"] == []


@patch("app.services.chatbot.query_services", side_effect=Exception("DB down"))
@patch("app.services.chatbot.claude_reply", side_effect=Exception("Claude down too"))
def test_both_db_and_claude_fail(mock_claude, mock_query, fresh_session):
    """If both DB and Claude fail after confirmation, should return safe static message."""
    generate_reply("I need food in Brooklyn", session_id=fresh_session)
    result = generate_reply("Yes, search", session_id=fresh_session)
    assert "yourpeer.nyc" in result["response"].lower() or "trouble" in result["response"].lower()
    assert result["services"] == []


@patch("app.services.chatbot.query_services", return_value=MOCK_ERROR_RESULTS)
@patch("app.services.chatbot.claude_reply", return_value="I can try to help with that.")
def test_query_error_falls_back(mock_claude, mock_query, fresh_session):
    """If query_services returns an error key after confirmation, should fall back to Claude."""
    generate_reply("I need food in Brooklyn", session_id=fresh_session)
    result = generate_reply("Yes, search", session_id=fresh_session)
    mock_claude.assert_called_once()
    assert result["response"] == "I can try to help with that."


# -----------------------------------------------------------------------
# SERVICE FOLLOW-UP (not enough slots)
# -----------------------------------------------------------------------

def test_service_needs_followup(fresh_session):
    """Service keyword without location should ask follow-up, not query DB."""
    result = send("I need food", session_id=fresh_session)
    assert result["follow_up_needed"] is True
    assert result["services"] == []
    assert "borough" in result["response"].lower() or "neighborhood" in result["response"].lower() or "area" in result["response"].lower()


# -----------------------------------------------------------------------
# GENERAL CONVERSATION
# -----------------------------------------------------------------------

@patch("app.services.chatbot.query_services")
@patch("app.services.chatbot.claude_reply", return_value="I understand. How can I help you find what you need?")
def test_general_conversation(mock_claude, mock_query, fresh_session):
    """Unrecognized messages should route to Claude for conversational response."""
    result = generate_reply("tell me more about that", session_id=fresh_session)
    mock_query.assert_not_called()
    mock_claude.assert_called_once()
    assert result["response"] == "I understand. How can I help you find what you need?"


# -----------------------------------------------------------------------
# MULTI-TURN SESSION STATE
# -----------------------------------------------------------------------

def test_multi_turn_slot_accumulation(fresh_session):
    """Slots should accumulate across turns within the same session."""
    r1, r2, r3 = send_multi(
        ["I need food", "Brooklyn", "Yes, search"],
        session_id=fresh_session,
    )
    assert r1["follow_up_needed"] is True
    assert r1["slots"].get("service_type") == "food"
    assert r2["follow_up_needed"] is True
    assert "brooklyn" in r2["slots"].get("location", "").lower()
    assert r3["result_count"] >= 1


def test_reset_then_new_search(fresh_session):
    """After reset, a new search should start from scratch."""
    r_food, r_reset, r_shelter = send_multi(
        ["I need food", "start over", "shelter"],
        session_id=fresh_session,
    )
    assert r_reset["slots"] == {}
    assert r_shelter["slots"].get("service_type") == "shelter"


# -----------------------------------------------------------------------
# PII REDACTION IN CHATBOT FLOW
# -----------------------------------------------------------------------

def test_pii_redacted_in_transcript(fresh_session):
    """PII should be redacted in the stored transcript but slots should still extract."""
    result = send(
        "My name is Sarah and I need food in Brooklyn",
        session_id=fresh_session,
    )
    assert result["slots"].get("service_type") == "food"

    stored = get_session_slots(fresh_session)
    transcript = stored.get("transcript", [])
    assert len(transcript) > 0
    last_msg = transcript[-1]["text"]
    assert "Sarah" not in last_msg
    assert "[NAME]" in last_msg
    assert "Brooklyn" in last_msg or "brooklyn" in last_msg


def test_phone_redacted_in_transcript(fresh_session):
    """Phone numbers should be redacted in transcript."""
    send("My number is 212-555-1234, I need food", session_id=fresh_session)

    stored = get_session_slots(fresh_session)
    transcript = stored.get("transcript", [])
    assert len(transcript) > 0
    last_msg = transcript[-1]["text"]
    assert "212-555-1234" not in last_msg
    assert "[PHONE]" in last_msg


# -----------------------------------------------------------------------
# SESSION ID GENERATION
# -----------------------------------------------------------------------

def test_session_id_generated_when_none():
    """If no session_id is provided, one should be generated."""
    result = send("hi")
    assert result["session_id"] is not None
    assert len(result["session_id"]) > 0
    clear_session(result["session_id"])


def test_session_id_preserved():
    """If session_id is provided, it should be returned unchanged."""
    result = send("hi", session_id="my-custom-id")
    assert result["session_id"] == "my-custom-id"
    clear_session("my-custom-id")


# -----------------------------------------------------------------------
# RESPONSE STRUCTURE VALIDATION
# -----------------------------------------------------------------------

def test_response_has_all_required_keys(fresh_session):
    """Every response should have all required keys for the ChatResponse model."""
    required_keys = [
        "session_id", "response", "follow_up_needed",
        "slots", "services", "result_count", "relaxed_search",
        "quick_replies",
    ]
    for msg in ["hi", "I need food", "thank you", "start over", "help"]:
        result = send(msg, session_id=fresh_session)
        for key in required_keys:
            assert key in result, f"Missing key '{key}' in response for: {msg}"


@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.claude_reply")
def test_relaxed_search_flag(mock_claude, mock_query, fresh_session):
    """relaxed_search should reflect whether the query was relaxed."""
    generate_reply("I need food in Brooklyn", session_id=fresh_session)
    result = generate_reply("Yes, search", session_id=fresh_session)
    assert result["relaxed_search"] is False

    mock_query.return_value = {**MOCK_QUERY_RESULTS, "relaxed": True}
    clear_session(fresh_session)
    generate_reply("I need food in Brooklyn", session_id=fresh_session)
    result2 = generate_reply("Yes, search", session_id=fresh_session)
    assert result2["relaxed_search"] is True
    assert "broadened" in result2["response"].lower()


# -----------------------------------------------------------------------
# CONFIRMATION FLOW & QUICK REPLIES
# -----------------------------------------------------------------------

def test_classify_confirmation_phrases():
    """Confirmation phrases should classify correctly."""
    for phrase in ["yes", "yeah", "ok", "sure", "go ahead", "yes please",
                   "correct", "yep", "yup", "do it", "find", "please"]:
        assert_classified(phrase, "confirm_yes")

    for phrase in ["yes search", "yes, search", "yes I want to search",
                   "please search", "search for that", "looks good",
                   "that's right", "thats correct", "confirm",
                   "go ahead and search", "yes that is correct"]:
        assert_classified(phrase, "confirm_yes")

    for phrase in ["change location", "different area", "wrong location"]:
        assert_classified(phrase, "confirm_change_location")

    for phrase in ["change service", "different service", "wrong service"]:
        assert_classified(phrase, "confirm_change_service")


def test_confirmation_step_triggered(fresh_session):
    """When both slots are filled, should return confirmation, not query."""
    result = send("I need food in Brooklyn", session_id=fresh_session)
    assert result["follow_up_needed"] is True
    assert "food" in result["response"].lower()
    assert "brooklyn" in result["response"].lower()
    assert len(result["quick_replies"]) >= 3


def test_change_location_during_confirmation(fresh_session):
    """User can change location during confirmation."""
    _, result = send_multi(
        ["I need food in Brooklyn", "Change location"],
        session_id=fresh_session,
    )
    assert result["slots"].get("location") is None
    assert result["slots"].get("service_type") == "food"
    assert len(result["quick_replies"]) > 0


def test_change_service_during_confirmation(fresh_session):
    """User can change service type during confirmation."""
    _, result = send_multi(
        ["I need food in Brooklyn", "Change service"],
        session_id=fresh_session,
    )
    assert result["slots"].get("service_type") is None
    assert "brooklyn" in result["slots"].get("location", "").lower()


def test_greeting_has_quick_replies(fresh_session):
    """Greeting response should include quick-reply category buttons."""
    result = send("hi", session_id=fresh_session)
    assert len(result["quick_replies"]) > 0
    labels = [qr["label"] for qr in result["quick_replies"]]
    assert any("Food" in l for l in labels)
    assert any("Shelter" in l for l in labels)


def test_reset_has_quick_replies(fresh_session):
    """Reset response should include quick-reply category buttons."""
    result = send("start over", session_id=fresh_session)
    assert len(result["quick_replies"]) > 0


def test_service_followup_has_quick_replies(fresh_session):
    """When only service type is known, follow-up should show borough buttons."""
    result = send("I need food", session_id=fresh_session)
    labels = [qr["label"] for qr in result.get("quick_replies", [])]
    assert any("Manhattan" in l or "Brooklyn" in l for l in labels), \
        f"Expected borough buttons, got: {labels}"


def test_new_input_clears_pending_confirmation(fresh_session):
    """Typing new service input during confirmation should re-extract and re-confirm."""
    _, result = send_multi(
        ["I need food in Brooklyn", "I need shelter in Queens"],
        session_id=fresh_session,
    )
    assert result["slots"].get("service_type") == "shelter"
    assert "queens" in result["slots"].get("location", "").lower()
    assert result["follow_up_needed"] is True


def test_results_have_post_search_quick_replies(fresh_session):
    """After results are shown, should offer new search and peer navigator buttons."""
    _, result = send_multi(
        ["I need food in Brooklyn", "Yes, search"],
        session_id=fresh_session,
    )
    assert result["result_count"] > 0
    labels = [qr["label"] for qr in result.get("quick_replies", [])]
    assert any("search" in l.lower() or "new" in l.lower() for l in labels)


def test_general_reply_does_not_retrigger_confirmation(fresh_session):
    """A general message like 'no' should NOT re-trigger confirmation from stale slots."""
    *_, result = send_multi(
        ["I need food in Manhattan", "Yes, search", "no"],
        session_id=fresh_session,
    )
    assert result["result_count"] == 0
    assert "search for" not in result["response"].lower()
    assert result["follow_up_needed"] is False


def test_no_after_escalation_does_not_confirm(fresh_session):
    """After escalation response, 'no' should route to general conversation."""
    *_, result = send_multi(
        ["I need food in Manhattan", "Yes, search",
         "Connect with peer navigator", "no"],
        session_id=fresh_session,
    )
    assert result["result_count"] == 0
    assert "search for" not in result["response"].lower()


# -----------------------------------------------------------------------
# BUG FIX REGRESSION TESTS
# -----------------------------------------------------------------------

def test_confirm_deny_breaks_loop(fresh_session):
    """Bug 1: Saying 'no' during confirmation should NOT loop forever."""
    r1, r2, r3 = send_multi(
        ["I need food in Brooklyn", "no", "no"],
        session_id=fresh_session,
    )
    assert r1["slots"].get("_pending_confirmation") is True
    assert r2["slots"].get("_pending_confirmation") is None
    assert "hold onto" in r2["response"].lower() or "no problem" in r2["response"].lower()
    assert len(r2["quick_replies"]) > 0
    assert "just to make sure" not in r3["response"].lower()


def test_confirm_deny_phrases():
    """Bug 1: All denial phrases should classify as 'confirm_deny'."""
    for phrase in ["no", "nah", "nope", "not yet", "hold on", "stop"]:
        assert_classified(phrase, "confirm_deny")

    for phrase in ["no thanks", "no thank you", "i changed my mind",
                   "not right now", "maybe later"]:
        result = _classify_message(phrase)
        assert result in ("confirm_deny", "thanks", "reset"), \
            f"'{phrase}' should classify as confirm_deny, thanks, or reset, got '{result}'"


def test_cancel_variants_reset():
    """Bug 2: 'cancel my search', 'please cancel' etc. should trigger reset."""
    for phrase in ["cancel", "cancel my search", "please cancel",
                   "i want to cancel", "cancel this"]:
        assert_classified(phrase, "reset")


def test_frustration_expanded_phrases():
    """Bug 3: Expanded frustration phrases should be detected."""
    for phrase in ["not what I needed", "wrong results", "these results are bad",
                   "thats not right", "not useful", "this sucks",
                   "useless", "that didnt help", "none of those work"]:
        assert_classified(phrase, "frustration")


def test_thanks_with_continuation_falls_through():
    """Bug 8: 'thanks but I need X' should NOT be classified as thanks."""
    assert_classified("thanks", "thanks")
    assert_classified("thank you", "thanks")

    for phrase in ["thanks but I need more options",
                   "thank you but I also want shelter",
                   "thanks but can you also search for food",
                   "thanks however I need something else"]:
        assert _classify_message(phrase) != "thanks", \
            f"'{phrase}' should NOT classify as thanks"


def test_empty_message_guard(fresh_session):
    """Bug 6: Empty string messages should return welcome, not hit Claude."""
    result = send("", session_id=fresh_session)
    assert "looking for" in result["response"].lower()
    assert len(result["quick_replies"]) == 9


def test_whitespace_message_guard(fresh_session):
    """Bug 6: Whitespace-only messages should return welcome, not hit Claude."""
    result = send("   ", session_id=fresh_session)
    assert "looking for" in result["response"].lower()
    assert len(result["quick_replies"]) == 9


def test_confused_classification():
    """Confusion phrases should classify as 'confused', not 'general'."""
    for phrase in ["I don't know what to do", "I dont know what to do",
                   "idk what to do", "I don't know", "I'm confused",
                   "I'm lost", "I'm overwhelmed", "I'm not sure what I need",
                   "what should I do", "where do I start", "what are my options"]:
        assert_classified(phrase, "confused")

    assert_classified("I need food", "service")
    assert_classified("hello", "greeting")


def test_confused_does_not_trigger_llm(fresh_session):
    """'I don't know what to do' should NOT reach the LLM or extract slots."""
    result = send("I don't know what to do", session_id=fresh_session)
    assert "figure it out" in result["response"].lower() or "okay" in result["response"].lower()
    assert len(result["quick_replies"]) >= 9
    assert result["slots"].get("service_type") is None
    assert result["slots"].get("_pending_confirmation") is None


def test_conversation_history_passed_to_llm(fresh_session):
    """Session transcript should be stored and available for LLM context."""
    result = send("I need food in Queens", session_id=fresh_session)
    slots = result["slots"]
    assert "transcript" in slots
    assert len(slots["transcript"]) >= 1

    entry = slots["transcript"][0]
    assert entry["role"] == "user"
    assert "food" in entry["text"].lower()
