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
    for phrase in ["help", "what is this", "who are you",
                   "list services", "show services"]:
        assert_classified(phrase, "help")
    # Capability questions now route to bot_question (more specific answers)
    for phrase in ["how does this work", "what can you do",
                   "why weren't you able to get my location"]:
        assert_classified(phrase, "bot_question")
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
    result = send("help", session_id=fresh_session)
    assert "free services" in result["response"].lower() or "find" in result["response"].lower()


def test_bot_question_route(fresh_session):
    """Bot capability questions should get direct, informative answers."""
    result = send("why weren't you able to get my location?", session_id=fresh_session)
    # Should explain location/capabilities, not show frustration response
    response_lower = result["response"].lower()
    assert "frustrat" not in response_lower
    assert "tried places" not in response_lower
    # Should mention location, browser, or capabilities
    assert any(w in response_lower for w in ["location", "browser", "borough", "neighborhood", "nyc"])


def test_bot_question_does_not_extract_slots(fresh_session):
    """Bot questions should not trigger slot extraction."""
    result = send("what can you search for?", session_id=fresh_session)
    assert result["slots"].get("service_type") is None
    assert result["slots"].get("_pending_confirmation") is None
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
    """If a valid UUID session_id is provided, it should be returned unchanged."""
    import uuid
    custom_id = str(uuid.uuid4())
    result = send("hi", session_id=custom_id)
    assert result["session_id"] == custom_id
    clear_session(custom_id)
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
    # Mock detect_crisis so LLM fail-open doesn't misclassify as crisis
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        for phrase in ["I don't know what to do", "I dont know what to do",
                       "idk what to do", "I don't know", "I'm confused",
                       "I'm lost", "I'm overwhelmed", "I'm not sure what I need",
                       "what should I do", "where do I start", "what are my options"]:
            assert_classified(phrase, "confused")
    assert_classified("I need food", "service")
    assert_classified("hello", "greeting")
def test_confused_does_not_trigger_llm(fresh_session):
    """'I don't know what to do' should NOT reach the LLM or extract slots."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        result = send("I don't know what to do", session_id=fresh_session)
    assert "figure it out" in result["response"].lower() or "okay" in result["response"].lower()
    assert len(result["quick_replies"]) >= 9
    assert result["slots"].get("service_type") is None
    assert result["slots"].get("_pending_confirmation") is None


# -----------------------------------------------------------------------
# EMOTIONAL AWARENESS
# -----------------------------------------------------------------------

def test_emotional_classification():
    """Emotional phrases should classify as 'emotional', not 'confused' or 'general'."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        for phrase in [
            "I'm feeling really down",
            "I'm feeling sad",
            "having a hard time",
            "having a rough day",
            "I'm scared",
            "feeling lonely",
            "I'm not okay",
            "I'm struggling",
            "stressed out",
            "nobody cares",
            "tired of everything",
            "feeling hopeless",
        ]:
            assert_classified(phrase, "emotional")


def test_emotional_does_not_catch_service_messages():
    """Messages with service intent should still classify as 'service'."""
    assert_classified("I need food", "service")
    assert_classified("I need shelter in Brooklyn", "service")
    assert_classified("I need mental health support", "service")
    # "feeling hungry" has no emotional phrase match — goes to slots
    assert_classified("I'm feeling hungry", "service")
    # Regression: emotional phrase + service intent → service, not emotional
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        assert_classified(
            "I'm struggling with addiction and need a treatment program in Manhattan",
            "service",
        )
        assert_classified(
            "I'm overwhelmed and need food in Brooklyn",
            "service",
        )


def test_emotional_distinct_from_confused():
    """'I'm feeling lost' should be 'emotional', not 'confused'.
    'I don't know what to do' should still be 'confused'."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        assert_classified("I'm feeling lost", "emotional")
        assert_classified("I feel stuck", "emotional")
        assert_classified("I don't know what to do", "confused")
        assert_classified("what are my options", "confused")


def test_emotional_response_has_peer_navigator(fresh_session):
    """Emotional messages should get a warm response with a peer navigator option."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        result = send("I'm feeling really down", session_id=fresh_session)
    # Should acknowledge feeling, not show a service menu
    assert "service" not in result["response"].lower() or "peer" in result["response"].lower()
    # Should NOT show 9 welcome category buttons
    labels = [qr["label"] for qr in result["quick_replies"]]
    assert "🍽️ Food" not in labels
    # Should offer peer navigator
    assert any("person" in qr["label"].lower() or "peer" in qr["value"].lower()
               for qr in result["quick_replies"])
    # Should not extract slots
    assert result["slots"].get("service_type") is None


def test_emotional_does_not_set_confirmation(fresh_session):
    """Emotional messages should never trigger the confirmation flow."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        result = send("I'm having a really rough day", session_id=fresh_session)
    assert result["slots"].get("_pending_confirmation") is None
    assert result["follow_up_needed"] is False


def test_emotional_static_fallback_without_llm(fresh_session):
    """Without LLM, emotional messages should use the static response."""
    with patch("app.services.chatbot.detect_crisis", return_value=None), \
         patch("app.services.chatbot._USE_LLM", False):
        result = send("I'm feeling really down", session_id=fresh_session)
    assert "hear you" in result["response"].lower()
    assert "peer navigator" in result["response"].lower()


def test_conversation_history_passed_to_llm(fresh_session):
    """Session transcript should be stored and available for LLM context."""
    result = send("I need food in Queens", session_id=fresh_session)
    slots = result["slots"]
    assert "transcript" in slots
    assert len(slots["transcript"]) >= 1
    entry = slots["transcript"][0]
    assert entry["role"] == "user"
    assert "food" in entry["text"].lower()


# -----------------------------------------------------------------------
# PENDING CONFIRMATION LEAK (#3)
# -----------------------------------------------------------------------

def test_escalation_clears_pending_confirmation(fresh_session):
    """Escalation during a pending confirmation should clear the flag."""
    # Get to confirmation
    r1 = send("I need food in Brooklyn", session_id=fresh_session)
    assert r1["follow_up_needed"] is True
    assert r1["slots"].get("_pending_confirmation") is True

    # Escalate instead of confirming
    r2 = send("Connect with peer navigator", session_id=fresh_session)
    assert "peer navigator" in r2["response"].lower()

    # The pending flag should be cleared
    from app.services.session_store import get_session_slots
    slots = get_session_slots(fresh_session)
    assert slots.get("_pending_confirmation") is None


def test_crisis_clears_pending_confirmation(fresh_session):
    """Crisis during a pending confirmation should clear the flag."""
    # Get to confirmation
    r1 = send("I need food in Brooklyn", session_id=fresh_session)
    assert r1["follow_up_needed"] is True

    # Trigger crisis — call generate_reply directly because send()
    # always mocks detect_crisis to None, overriding our mock.
    from app.services.chatbot import generate_reply
    with patch("app.services.chatbot.detect_crisis",
               return_value=("suicide_self_harm", "Crisis response")), \
         patch("app.services.chatbot.claude_reply", return_value=""), \
         patch("app.services.chatbot.query_services"):
        generate_reply("I want to hurt myself", session_id=fresh_session)

    # The pending flag should be cleared
    from app.services.session_store import get_session_slots
    slots = get_session_slots(fresh_session)
    assert slots.get("_pending_confirmation") is None


# -----------------------------------------------------------------------
# CONTEXT-AWARE "NO" (#4)
# -----------------------------------------------------------------------

def test_no_after_escalation_routes_to_general(fresh_session):
    """'No' after escalation should NOT re-trigger search confirmation."""
    # Fill slots and confirm
    r1 = send("I need food in Brooklyn", session_id=fresh_session)
    assert r1["follow_up_needed"] is True

    # Escalate (this clears pending confirmation)
    r2 = send("Connect with peer navigator", session_id=fresh_session)
    assert "peer navigator" in r2["response"].lower()

    # Say "no" — should be about the escalation, not the search
    r3 = send("no", session_id=fresh_session)
    assert "change your mind" in r3["response"].lower() or "anything else" in r3["response"].lower()
    # Should NOT show the food/Brooklyn confirmation
    assert "food" not in r3["response"].lower()


def test_yes_after_escalation_shows_peer_navigator(fresh_session):
    """'Yes' after escalation should show peer navigator info, not run a search."""
    r1 = send("I need food in Brooklyn", session_id=fresh_session)
    assert r1["follow_up_needed"] is True

    # Escalate
    r2 = send("Connect with peer navigator", session_id=fresh_session)
    assert "peer navigator" in r2["response"].lower()

    # Say "yes" — should show peer navigator info again, not execute the food search
    r3 = send("yes", session_id=fresh_session)
    assert "peer navigator" in r3["response"].lower()
    assert r3["result_count"] == 0  # No service results


def test_yes_after_emotional_routes_to_escalation(fresh_session):
    """'Yes' after an emotional response should connect to peer navigator."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        r1 = send("I'm feeling really down", session_id=fresh_session)
    # The emotional response offers a peer navigator
    assert any("person" in qr["label"].lower() or "peer" in qr["value"].lower()
               for qr in r1["quick_replies"])

    # User says "yes" — means "yes, connect me with a person"
    r2 = send("yes", session_id=fresh_session)
    assert "peer navigator" in r2["response"].lower()


def test_no_after_emotional_is_gentle(fresh_session):
    """'No' after an emotional response should be gentle, not push services."""
    with patch("app.services.chatbot.detect_crisis", return_value=None):
        r1 = send("I'm feeling really down", session_id=fresh_session)

    r2 = send("no", session_id=fresh_session)
    assert "okay" in r2["response"].lower() or "ready" in r2["response"].lower()
    # Should NOT show the full service menu
    labels = [qr["label"] for qr in r2.get("quick_replies", [])]
    assert "🍽️ Food" not in labels


def test_yes_still_confirms_search_normally(fresh_session):
    """Context-aware yes should not break normal search confirmation."""
    r1 = send("I need food in Brooklyn", session_id=fresh_session)
    assert r1["follow_up_needed"] is True

    # "yes" with no prior escalation/emotional should still run the search
    r2 = send("Yes, search", session_id=fresh_session)
    assert r2["result_count"] >= 1


# -----------------------------------------------------------------------
# JUST CHATTING MODE (#5)
# -----------------------------------------------------------------------

def test_general_response_no_buttons_after_conversation(fresh_session):
    """After the first turn, general responses should not push service buttons."""
    # First general message — may show buttons (first turn)
    r1 = send("how's it going?", session_id=fresh_session)

    # Second general message — should NOT push the full 9-category menu
    r2 = send("just thinking about stuff", session_id=fresh_session)
    labels = [qr["label"] for qr in r2.get("quick_replies", [])]
    # Should not have the full welcome menu
    assert "🍽️ Food" not in labels


def test_general_response_no_buttons_with_service_intent(fresh_session):
    """General messages mid-search should not re-show the service menu."""
    # Start a search
    send("I need food", session_id=fresh_session)

    # General follow-up mid-search
    r2 = send("ok cool", session_id=fresh_session)
    labels = [qr["label"] for qr in r2.get("quick_replies", [])]
    assert "🍽️ Food" not in labels


# -----------------------------------------------------------------------
# BOT RESPONSE PII REDACTION IN AUDIT LOG
# -----------------------------------------------------------------------

def test_log_turn_redacts_bot_response_pii():
    """_log_turn should redact PII from bot responses before storing."""
    from app.services.chatbot import _log_turn
    from app.services.audit_log import get_recent_events, clear_audit_log

    clear_audit_log()
    _log_turn(
        session_id="s-pii-test",
        user_msg="My name is [NAME]",
        result={
            "response": "Hi Bryan! I can help you find services.",
            "slots": {"service_type": "food"},
        },
        category="general",
    )

    events = get_recent_events()
    bot_response = events[0]["bot_response"]
    assert "Bryan" not in bot_response, "PII should be redacted from bot response"
    assert "[NAME]" in bot_response


def test_log_turn_redacts_phone_in_bot_response():
    """_log_turn should redact phone numbers echoed in bot responses."""
    from app.services.chatbot import _log_turn
    from app.services.audit_log import get_recent_events, clear_audit_log

    clear_audit_log()
    _log_turn(
        session_id="s-pii-test-2",
        user_msg="[PHONE]",
        result={
            "response": "I see your number is 212-555-1234. Let me look that up.",
            "slots": {},
        },
        category="general",
    )

    events = get_recent_events()
    bot_response = events[0]["bot_response"]
    assert "212-555-1234" not in bot_response, "Phone should be redacted from bot response"
    assert "[PHONE]" in bot_response


# -----------------------------------------------------------------------
# GEOLOCATION COORDINATE PRIORITY
# -----------------------------------------------------------------------

def test_text_location_overrides_stored_coords(fresh_session):
    """When user provides a text location after using 'near me', the query
    should use the text location and NOT the stored browser coordinates."""
    from unittest.mock import patch, call
    from app.services.chatbot import generate_reply
    from conftest import MOCK_QUERY_RESULTS

    with patch("app.services.chatbot.claude_reply", return_value="How can I help?"), \
         patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS) as mock_query, \
         patch("app.services.chatbot.detect_crisis", return_value=None):

        # Step 1: User says "food near me" with browser coordinates (Harlem)
        generate_reply("food near me", session_id=fresh_session, latitude=40.8116, longitude=-73.9465)
        # Step 2: Confirm the near-me search
        generate_reply("Yes, search", session_id=fresh_session)

        # Step 3: New search with a TEXT location (Midtown East)
        generate_reply("mental health in Midtown East", session_id=fresh_session)
        generate_reply("Yes, search", session_id=fresh_session)

        # The LAST call to query_services should use Midtown East,
        # NOT the Harlem coordinates
        last_call = mock_query.call_args
        assert last_call.kwargs.get("latitude") is None or last_call[1].get("latitude") is None, \
            "Stored coordinates should not override text location"
        location_arg = last_call.kwargs.get("location") or last_call[1].get("location")
        assert location_arg is not None, "Text location should be passed"
        assert "near_me" not in str(location_arg).lower(), "Should not use near-me sentinel"


# -----------------------------------------------------------------------
# PRIVACY QUESTIONS — CLASSIFICATION
# -----------------------------------------------------------------------

def test_classify_privacy_questions():
    """Privacy-related questions should classify as bot_question."""
    privacy_questions = [
        "is this private",
        "is this confidential",
        "is this safe",
        "are you recording me",
        "who can see this",
        "can anyone see my messages",
        "do you share my information",
        "do you store my data",
        "can ICE see this",
        "can the police see what I said",
        "will this affect my benefits",
        "can my case worker see this",
        "can the shelter see what I wrote",
        "how do i delete my conversation",
        "do you know who I am",
        "do you know my name",
        "do you save my info",
        "do you track me",
        "is this anonymous",
    ]
    for phrase in privacy_questions:
        assert_classified(phrase, "bot_question")


def test_privacy_not_confused_with_service():
    """Privacy questions should not be misclassified as service requests."""
    # "benefits" is also an "other" service keyword, but in privacy context
    # "will this affect my benefits" should be bot_question not service
    assert_classified("will this affect my benefits", "bot_question")


# -----------------------------------------------------------------------
# STATIC BOT ANSWERS — PATTERN MATCHING
# -----------------------------------------------------------------------

def test_static_bot_answer_geolocation_failure():
    """Geolocation failure questions get a specific answer."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Why couldn't you get my location?")
    assert "permission" in response.lower() or "denied" in response.lower()
    assert "neighborhood" in response.lower() or "borough" in response.lower()


def test_static_bot_answer_geolocation_general():
    """General geolocation questions get a relevant answer."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("How does location work?")
    assert "gps" in response.lower() or "location" in response.lower()


def test_static_bot_answer_outside_nyc():
    """Outside-NYC questions mention 211."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Can you search outside NYC?")
    assert "211" in response
    assert "new york" in response.lower() or "nyc" in response.lower()


def test_static_bot_answer_services_list():
    """Service category questions list available categories."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("What services can you search for?")
    assert "food" in response.lower()
    assert "shelter" in response.lower()
    assert "legal" in response.lower()


def test_static_bot_answer_privacy_ice():
    """ICE-related privacy questions give specific reassurance."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Can ICE see my conversation?")
    assert "ice" in response.lower()
    assert "government" in response.lower() or "identifying" in response.lower()


def test_static_bot_answer_privacy_police():
    """Police-related questions give specific reassurance."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Do you share with the police?")
    assert "law enforcement" in response.lower()


def test_static_bot_answer_privacy_benefits():
    """Benefits-impact questions give specific reassurance."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Will this affect my benefits or case?")
    assert "benefits" in response.lower()
    assert "case" in response.lower() or "provider" in response.lower()


def test_static_bot_answer_privacy_who_can_see():
    """Visibility questions reassure no one else can see."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Can anyone see what I said?")
    assert "no one" in response.lower() or "nobody" in response.lower()


def test_static_bot_answer_privacy_delete():
    """Delete/clear questions explain how."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("How do I delete my conversation?")
    assert "start over" in response.lower()


def test_static_bot_answer_privacy_identity():
    """Identity questions confirm anonymity."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Do you know my name?")
    assert "don't know" in response.lower() or "do not know" in response.lower()


def test_static_bot_answer_privacy_general():
    """General privacy question gets comprehensive answer."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Is this confidential?")
    assert "private" in response.lower() or "anonymous" in response.lower()


def test_static_bot_answer_how_it_works():
    """'How does this work' gets an explanation."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("How does this work?")
    assert "database" in response.lower() or "search" in response.lower()


def test_static_bot_answer_default():
    """Unknown bot questions get a generic but useful answer."""
    from app.services.chatbot import _static_bot_answer
    response = _static_bot_answer("Why is the sky blue?")
    assert "service" in response.lower()


# -----------------------------------------------------------------------
# SERVICE DETAIL IN CONFIRMATION
# -----------------------------------------------------------------------

def test_confirmation_uses_service_detail(fresh_session):
    """Confirmation message should use service_detail when available."""
    from app.services.chatbot import _build_confirmation_message
    slots = {"service_type": "medical", "service_detail": "dental care", "location": "Brooklyn"}
    msg = _build_confirmation_message(slots)
    assert "dental care" in msg.lower()
    assert "health care" not in msg.lower(), "Should use detail, not generic label"


def test_confirmation_falls_back_to_label(fresh_session):
    """Confirmation message should use generic label when no service_detail."""
    from app.services.chatbot import _build_confirmation_message
    slots = {"service_type": "food", "location": "Queens"}
    msg = _build_confirmation_message(slots)
    assert "food" in msg.lower()


def test_change_service_clears_detail(fresh_session):
    """Changing service type during confirmation should clear service_detail."""
    from app.services.session_store import get_session_slots

    # Start a dental care search
    send("I need dental care", session_id=fresh_session)
    send("Brooklyn", session_id=fresh_session)

    # At confirmation, change service
    send("Change service", session_id=fresh_session)

    slots = get_session_slots(fresh_session)
    assert slots.get("service_detail") is None, "service_detail should be cleared"
    assert slots.get("service_type") is None, "service_type should be cleared"


# -----------------------------------------------------------------------
# BOT QUESTION HANDLER — FULL FLOW
# -----------------------------------------------------------------------

def test_bot_question_privacy_gets_specific_response(fresh_session):
    """Privacy questions should get a specific answer, not generic overview."""
    result = send("Is this private? Can anyone see what I type?", session_id=fresh_session)
    response = result["response"].lower()
    # Should mention privacy, not just list service categories
    assert "private" in response or "anonymous" in response or "no one" in response


def test_bot_question_geolocation_gets_specific_response(fresh_session):
    """Geolocation questions should explain why it might fail."""
    result = send("Why couldn't you get my location?", session_id=fresh_session)
    response = result["response"].lower()
    assert "permission" in response or "browser" in response or "neighborhood" in response


def test_bot_question_outside_nyc_gets_specific_response(fresh_session):
    """Outside-NYC questions should mention coverage limitation."""
    result = send("Can you search outside NYC?", session_id=fresh_session)
    response = result["response"].lower()
    assert "new york" in response or "nyc" in response or "five boroughs" in response
