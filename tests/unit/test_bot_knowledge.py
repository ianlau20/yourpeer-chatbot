"""Tests for the bot self-knowledge module.

Verifies that:
1. Topic matching works for all expected question types
2. Live capability sourcing returns real data
3. The LLM context generation includes all required sections
4. The static handler routes correctly through bot_knowledge
5. Bot question phrases classify correctly
"""
import pytest
from app.services.bot_knowledge import (
    answer_question, build_capability_context, TOPICS,
    _get_service_categories, _get_pii_categories, _get_location_count,
)
from app.services.classifier import _classify_action
from app.services.responses import _static_bot_answer


class TestLiveCapabilitySourcing:
    """Capabilities should be sourced from actual code, not hardcoded."""

    def test_service_categories_from_code(self):
        cats = _get_service_categories()
        assert "food" in cats
        assert "shelter" in cats
        assert "medical" in cats
        assert len(cats) >= 9

    def test_pii_categories_from_code(self):
        pii = _get_pii_categories()
        assert "phone" in pii
        assert "ssn" in pii
        assert "name" in pii
        assert len(pii) >= 8

    def test_location_count_from_code(self):
        count = _get_location_count()
        assert count >= 60  # we know there are 68+


class TestTopicMatching:
    """Every topic should match its expected question phrasings."""

    @pytest.mark.parametrize("question", [
        "What can you do?",
        "What services do you offer?",
        "What can you help me with?",
        "What can you search for?",
    ])
    def test_services_topic(self, question):
        answer = answer_question(question)
        assert answer is not None
        assert "food" in answer.lower()

    @pytest.mark.parametrize("question", [
        "Why couldn't you get my location?",
        "Why can't you find my location?",
        "My location isn't working",
    ])
    def test_location_fail_topic(self, question):
        answer = answer_question(question)
        assert answer is not None
        assert "permission" in answer.lower() or "fail" in answer.lower() \
            or "browser" in answer.lower()

    @pytest.mark.parametrize("question", [
        "What happens to my information?",
        "Is this private?",
        "Is this safe to use?",
        "Is my data safe?",
        "What do you do with my data?",
    ])
    def test_privacy_general_topic(self, question):
        answer = answer_question(question)
        assert answer is not None
        assert "private" in answer.lower() or "anonymous" in answer.lower()

    @pytest.mark.parametrize("question", [
        "Can ICE see my information?",
        "Will immigration find out?",
        "Are you connected to ICE?",
    ])
    def test_privacy_ice_topic(self, question):
        answer = answer_question(question)
        assert answer is not None
        assert "ice" in answer.lower() or "government" in answer.lower()

    @pytest.mark.parametrize("question", [
        "Will this affect my benefits?",
        "Can my case worker see this?",
    ])
    def test_privacy_benefits_topic(self, question):
        answer = answer_question(question)
        assert answer is not None
        assert "benefits" in answer.lower() or "case" in answer.lower()

    def test_coverage_topic(self):
        answer = answer_question("Do you work outside New York?")
        assert answer is not None
        assert "211" in answer

    def test_how_it_works_topic(self):
        answer = answer_question("How does this work?")
        assert answer is not None
        assert "streetlives" in answer.lower() or "database" in answer.lower()

    def test_limitations_topic(self):
        answer = answer_question("What are your limitations?")
        assert answer is not None
        assert "can't" in answer.lower() or "cannot" in answer.lower()

    def test_no_match_returns_none(self):
        assert answer_question("I need food in Brooklyn") is None
        assert answer_question("hello") is None


class TestCapabilityContext:
    """The LLM context should include all required sections."""

    def test_includes_service_categories(self):
        ctx = build_capability_context()
        assert "Food" in ctx
        assert "Shelter" in ctx
        assert "Legal" in ctx

    def test_includes_pii_types(self):
        ctx = build_capability_context()
        assert "ssn" in ctx or "SSN" in ctx
        assert "phone" in ctx

    def test_includes_location_count(self):
        ctx = build_capability_context()
        assert "68" in ctx or "neighborhoods" in ctx

    def test_includes_privacy(self):
        ctx = build_capability_context()
        assert "ICE" in ctx
        assert "law enforcement" in ctx
        assert "auto-expires" in ctx

    def test_includes_crisis(self):
        ctx = build_capability_context()
        assert "crisis" in ctx.lower()

    def test_includes_emotional(self):
        ctx = build_capability_context()
        assert "emotional" in ctx.lower() or "shame" in ctx.lower()


class TestStaticHandlerIntegration:
    """_static_bot_answer should route through bot_knowledge."""

    def test_location_question(self):
        answer = _static_bot_answer("Why couldn't you get my location?")
        assert "permission" in answer.lower() or "fail" in answer.lower()

    def test_privacy_question(self):
        answer = _static_bot_answer("What happens to my information?")
        assert "private" in answer.lower() or "anonymous" in answer.lower()

    def test_unknown_question_gets_default(self):
        answer = _static_bot_answer("Why is the sky blue?")
        assert "verified social services" in answer.lower()


class TestBotQuestionPhraseClassification:
    """New privacy question phrases should classify as bot_question."""

    @pytest.mark.parametrize("phrase", [
        "what happens to my information",
        "what do you do with my data",
        "where does my information go",
        "is my information safe",
        "do you sell my data",
    ])
    def test_privacy_phrases_classify_as_bot_question(self, phrase):
        action = _classify_action(phrase)
        assert action == "bot_question", \
            f"'{phrase}' should classify as bot_question, got '{action}'"


# =====================================================================
# Previously untested topics
# =====================================================================

class TestUntestedTopics:
    """Cover the 6 topics that had no test coverage."""

    def test_language_topic(self):
        answer = answer_question("Do you speak Spanish?")
        assert answer is not None
        assert "english" in answer.lower() or "language" in answer.lower()

    def test_peer_navigator_topic(self):
        answer = answer_question("What is a peer navigator?")
        assert answer is not None
        assert "lived experience" in answer.lower() or "real person" in answer.lower()

    def test_privacy_delete_topic(self):
        answer = answer_question("How do I delete my chat history?")
        assert answer is not None
        assert "start over" in answer.lower()

    def test_privacy_identity_topic(self):
        answer = answer_question("Do you know my name?")
        assert answer is not None
        assert "don't know who" in answer.lower() or "anonymous" in answer.lower()

    def test_privacy_police_topic(self):
        answer = answer_question("Can the police see my messages?")
        assert answer is not None
        assert "law enforcement" in answer.lower() or "police" in answer.lower()

    def test_privacy_visibility_topic(self):
        answer = answer_question("Who can see my conversation?")
        assert answer is not None
        assert "no one" in answer.lower() or "no one else" in answer.lower()


# =====================================================================
# Multi-topic collision tests
# =====================================================================

class TestTopicCollisions:
    """When a message matches multiple topics, the most relevant should win."""

    def test_location_privacy_collision(self):
        """'Is my location data private?' → should be privacy, not location_how."""
        answer = answer_question("Is my location data private?")
        assert answer is not None
        assert "private" in answer.lower() or "anonymous" in answer.lower()
        # Should NOT get the location_how answer about GPS
        assert "tap 'use my location'" not in answer.lower()

    def test_police_location_collision(self):
        """'Can police see my location?' → should be privacy_police, not location."""
        answer = answer_question("Can police see my location?")
        assert answer is not None
        assert "law enforcement" in answer.lower() or "police" in answer.lower()

    def test_ice_share_collision(self):
        """'Do you share info with ICE or police?' → should be ICE (more specific)."""
        answer = answer_question("Do you share information with ICE or police?")
        assert answer is not None
        assert "ice" in answer.lower()

    def test_delete_privacy_collision(self):
        """'How do I delete my data?' → should be delete, not general privacy."""
        answer = answer_question("How do I delete my data?")
        assert answer is not None
        assert "start over" in answer.lower()

    def test_services_coverage_collision(self):
        """'What services outside NYC?' → coverage should win (more specific)."""
        answer = answer_question("What services can you find outside NYC?")
        assert answer is not None
        # Coverage mentions 211; services doesn't
        assert "211" in answer or "outside" in answer.lower()


# =====================================================================
# False positive guards
# =====================================================================

class TestFalsePositives:
    """Non-bot-questions should NOT match any topic."""

    @pytest.mark.parametrize("msg", [
        "I need food in Brooklyn",
        "shelter in Queens",
        "I'm scared",
        "thank you",
        "yes",
        "no",
        "Start over",
        "I'm 17 and homeless",
        "hello",
        "I'm feeling down",
    ])
    def test_service_and_action_messages_no_match(self, msg):
        assert answer_question(msg) is None


# =====================================================================
# Integration: bot_question routing through generate_reply
# =====================================================================

class TestBotQuestionRouting:
    """Bot questions should route to the bot_question handler
    and return answers from bot_knowledge."""

    def test_privacy_question_through_chatbot(self):
        from conftest import send
        import uuid
        sid = f"test-{uuid.uuid4().hex[:8]}"
        r = send("What happens to my information?", session_id=sid)
        resp = r["response"].lower()
        assert "private" in resp or "anonymous" in resp or "store" in resp

    def test_location_question_through_chatbot(self):
        from conftest import send
        import uuid
        sid = f"test-{uuid.uuid4().hex[:8]}"
        r = send("Why couldn't you get my location?", session_id=sid)
        resp = r["response"].lower()
        assert "permission" in resp or "browser" in resp or "gps" in resp

    def test_services_question_through_chatbot(self):
        from conftest import send
        import uuid
        sid = f"test-{uuid.uuid4().hex[:8]}"
        r = send("What can you help me with?", session_id=sid)
        resp = r["response"].lower()
        assert "food" in resp or "shelter" in resp
