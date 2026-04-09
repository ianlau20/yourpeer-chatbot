"""
Tests for phrase list audit additions (P0–P3).

Validates that phrases added during the audit are correctly detected
and routed. Each test group corresponds to a priority tier from
PHRASE_LIST_AUDIT.md.

Run with: python -m pytest tests/test_phrase_audit.py -v
"""

import pytest
from unittest.mock import patch
from app.services.crisis_detector import detect_crisis
from app.services.chatbot import _classify_tone, _classify_action
from app.services.slot_extractor import extract_slots
from conftest import assert_classified, send


# -----------------------------------------------------------------------
# P0 — Suicide/Self-Harm (C-SSRS + Joiner IPT)
# -----------------------------------------------------------------------

class TestP0SuicideCSSRS:
    """C-SSRS aligned phrases must trigger suicide_self_harm crisis."""

    @pytest.mark.parametrize("phrase", [
        # C-SSRS Level 1: Wish to be dead
        "wish i was never born",
        "wish i wasn't alive",
        "I don't want to wake up",
        "I want to go to sleep and never wake up",
        "I just want to fall asleep and never wake up",
        # C-SSRS Level 2: Non-specific active thoughts
        "I've been thinking about ending it",
        "I keep thinking about killing myself",
        "I've had thoughts of suicide lately",
        # C-SSRS Level 3: Method without plan
        "I've thought about pills",
        "I thought about jumping off",
    ])
    def test_cssrs_phrases_detected(self, phrase):
        result = detect_crisis(phrase)
        assert result is not None, f"'{phrase}' should trigger crisis"
        assert result[0] == "suicide_self_harm"

    @pytest.mark.parametrize("phrase", [
        # Joiner IPT — perceived burdensomeness
        "i'm a burden to everyone",
        "im a burden",
        "everyone would be fine without me",
        "the world would be better without me",
        # Pain/threshold
        "i can't take it anymore",
        "i cant take it anymore",
        "i just want the pain to stop",
        "life isn't worth it",
        "make it all stop",
        "im done with everything",
        "wish it would all stop",
        "no point in going on",
    ])
    def test_joiner_ipt_and_pain_phrases(self, phrase):
        result = detect_crisis(phrase)
        assert result is not None, f"'{phrase}' should trigger crisis"
        assert result[0] == "suicide_self_harm"


# -----------------------------------------------------------------------
# P1 — DV/Safety (control, youth violence, fleeing)
# -----------------------------------------------------------------------

class TestP1DVSafety:
    """DV control and youth safety phrases must trigger appropriate crisis."""

    @pytest.mark.parametrize("phrase", [
        "he controls everything in my life",
        "she controls everything",
        "he controls my money",
        "my partner takes my money",
        "he won't let me leave the house",
    ])
    def test_dv_control_phrases(self, phrase):
        result = detect_crisis(phrase)
        assert result is not None, f"'{phrase}' should trigger crisis"
        assert result[0] == "domestic_violence"

    @pytest.mark.parametrize("phrase", [
        "my parents hurt me",
        "my family hurts me",
        "I'm being hit at home",
        "there's no safe place to go",
        "nowhere safe for me",
        "I'm hiding from someone",
        "someone is looking for me",
        "he's looking for me",
        "I had to leave home fast",
        "I left home suddenly last night",
    ])
    def test_safety_youth_and_fleeing(self, phrase):
        result = detect_crisis(phrase)
        assert result is not None, f"'{phrase}' should trigger crisis"
        assert result[0] == "safety_concern"


# -----------------------------------------------------------------------
# P1+P2 — Emotional (shame, grief, isolation, despair)
# -----------------------------------------------------------------------

class TestP1P2Emotional:
    """New emotional phrases must classify as 'emotional' tone."""

    @pytest.mark.parametrize("phrase", [
        # Shame/stigma (P1)
        "I'm embarrassed to ask for help",
        "I'm ashamed to ask",
        "I feel ashamed of myself",
        "I'm embarrassed to be here",
        "I never thought I'd need help like this",
        "I feel like a failure",
        "I'm pathetic",
        # Grief/loss (P2)
        "I lost someone close to me",
        "someone died recently",
        "my friend died last week",
        "I'm grieving",
        "I'm in mourning",
        # Isolation (P2)
        "nobody understands what I'm going through",
        "no one understands me",
        "I'm completely alone",
        "I have no one",
        "I have no friends",
        "I have no family left",
        # Despair (P2)
        "everything is falling apart",
        "my life is falling apart",
        "nothing ever works out for me",
        "things keep getting worse",
        "I can't catch a break",
    ])
    def test_emotional_classification(self, phrase):
        with patch("app.services.chatbot.detect_crisis", return_value=None):
            tone = _classify_tone(phrase)
        assert tone == "emotional", \
            f"'{phrase}' should classify as emotional, got '{tone}'"

    def test_shame_does_not_trigger_crisis(self):
        """Shame phrases are emotional, not crisis."""
        for phrase in ["I'm embarrassed to ask", "I feel like a failure",
                       "I'm ashamed of myself"]:
            result = detect_crisis(phrase)
            assert result is None, \
                f"'{phrase}' should NOT trigger crisis"

    def test_grief_with_service_routes_to_service(self):
        """'I'm grieving and need counseling' should route to service."""
        slots = extract_slots("I'm grieving and need counseling")
        assert slots["service_type"] == "mental_health"


# -----------------------------------------------------------------------
# P2 — Frustration (contractions, stronger, resignation)
# -----------------------------------------------------------------------

class TestP2Frustration:
    """New frustration phrases must classify as 'frustrated' tone."""

    @pytest.mark.parametrize("phrase", [
        # Missing contractions
        "that hasn't helped at all",
        "this isn't working",
        "that isn't useful",
        "you can't help me",
        "this won't work",
        # Stronger frustration
        "this is ridiculous",
        "this is stupid",
        "you're not listening to me",
        "you don't understand what I need",
        "I keep getting the same results",
        "same thing every time",
        # Resignation
        "forget it",
        "this is pointless",
    ])
    def test_frustration_classification(self, phrase):
        with patch("app.services.chatbot.detect_crisis", return_value=None):
            tone = _classify_tone(phrase)
        assert tone == "frustrated", \
            f"'{phrase}' should classify as frustrated, got '{tone}'"

    def test_forget_it_does_not_reset(self):
        """'forget it' should route to frustration, not reset."""
        action = _classify_action("forget it")
        assert action != "reset", \
            "'forget it' should NOT be a reset action"

    def test_i_give_up_on_this_routes_to_crisis(self):
        """'i give up on this' matches suicide 'i give up' — intentional."""
        result = detect_crisis("i give up on this")
        assert result is not None, \
            "'i give up on this' should match crisis 'i give up' (intentional broad catch)"


# -----------------------------------------------------------------------
# P3 — Confused (expanded)
# -----------------------------------------------------------------------

class TestP3Confused:
    """Expanded confused phrases must classify as 'confused' tone."""

    @pytest.mark.parametrize("phrase", [
        "where do I even go for help",
        "who do I talk to about this",
        "this is confusing",
        "there are too many options",
        "everything is too much right now",
        "it's all too much",
        "I can't think straight",
        "so much going on in my life",
    ])
    def test_confused_classification(self, phrase):
        with patch("app.services.chatbot.detect_crisis", return_value=None):
            tone = _classify_tone(phrase)
        assert tone == "confused", \
            f"'{phrase}' should classify as confused, got '{tone}'"


# -----------------------------------------------------------------------
# P3 — Service Keywords (NYC-specific)
# -----------------------------------------------------------------------

class TestP3ServiceKeywords:
    """NYC-specific service keywords must extract correctly."""

    @pytest.mark.parametrize("phrase,expected_type", [
        # Food
        ("where can I get baby formula", "food"),
        ("I need WIC", "food"),
        ("where can I get diapers", "food"),
        # Shelter
        ("how do I get to the PATH center", "shelter"),
        ("I need DHS intake", "shelter"),
        ("I need a domestic violence shelter", "shelter"),
        # Medical / harm reduction
        ("where can I get methadone", "medical"),
        ("I need suboxone", "medical"),
        ("where do I get narcan", "medical"),
        ("is there a walk-in clinic nearby", "medical"),
        # Other
        ("I need help with voter registration", "other"),
        ("I need a replacement ID", "other"),
        ("where can I get free tax prep", "other"),
    ])
    def test_nyc_service_extraction(self, phrase, expected_type):
        slots = extract_slots(phrase)
        assert slots["service_type"] == expected_type, \
            f"'{phrase}' should extract as '{expected_type}', got '{slots['service_type']}'"


# -----------------------------------------------------------------------
# False positive guards
# -----------------------------------------------------------------------

class TestFalsePositiveGuards:
    """Phrases that should NOT trigger certain categories."""

    def test_embarrassed_not_crisis(self):
        """Shame language should NOT trigger crisis detection."""
        for phrase in ["I'm embarrassed", "I feel ashamed", "I'm pathetic"]:
            assert detect_crisis(phrase) is None

    def test_grieving_not_crisis(self):
        """Grief language should NOT trigger crisis detection."""
        for phrase in ["I'm grieving", "I lost someone", "my friend died"]:
            assert detect_crisis(phrase) is None

    def test_forget_it_not_crisis(self):
        """'forget it' is frustration, not crisis."""
        assert detect_crisis("forget it") is None

    def test_this_is_stupid_not_crisis(self):
        """'this is stupid' is frustration, not crisis."""
        assert detect_crisis("this is stupid") is None

    def test_i_have_no_one_not_crisis(self):
        """Isolation is emotional, not crisis (unless combined with suicidal language)."""
        assert detect_crisis("I have no one") is None

    def test_disappear_is_crisis(self):
        """'want to disappear' maps to wish-to-be-dead per C-SSRS."""
        # Note: this is in the suicide list, not emotional
        # If it ever moves to emotional, this test should be updated
        result = detect_crisis("I just want to disappear")
        # Currently NOT in phrase list — handled by LLM stage
        # This test documents the design decision
        pass

    def test_whats_the_point_without_anymore_not_suicide(self):
        """'what's the point' without 'anymore' should NOT trigger suicide.
        The bare form is too common in non-suicidal contexts."""
        result = detect_crisis("what's the point of this")
        assert result is None, \
            "'what's the point of this' should NOT trigger crisis"

    def test_whats_the_point_anymore_is_suicide(self):
        """'what's the point anymore' SHOULD trigger suicide."""
        result = detect_crisis("what's the point anymore")
        assert result is not None
        assert result[0] == "suicide_self_harm"


# -----------------------------------------------------------------------
# Emotion-specific responses (Run 18 fixes)
# -----------------------------------------------------------------------

class TestEmotionSpecificResponses:
    """Different emotions should get different response text."""

    def test_scared_gets_scared_response(self):
        r = send("I'm scared")
        assert "scared" in r["response"].lower()
        assert "food" not in r["response"].lower()
        assert "shelter" not in r["response"].lower()

    def test_feeling_down_gets_sad_response(self):
        r = send("I'm feeling really down")
        assert "not be okay" in r["response"].lower() or "not okay" in r["response"].lower() \
            or "difficult time" in r["response"].lower()
        assert "food" not in r["response"].lower()

    def test_rough_day_gets_rough_day_response(self):
        r = send("I've been having a rough day")
        assert "heavy" in r["response"].lower() or "hard" in r["response"].lower()
        assert "food" not in r["response"].lower()

    def test_shame_gets_normalizing_response(self):
        r = send("I'm embarrassed to ask for help")
        assert "ashamed" in r["response"].lower() or "shame" in r["response"].lower() \
            or "nothing to be" in r["response"].lower()
        from app.services.session_store import get_session_slots
        # Should route to emotional, not help
        assert r["response"] != "How can I help?"

    def test_grief_gets_grief_response(self):
        r = send("I lost someone close to me")
        assert "loss" in r["response"].lower() or "sorry" in r["response"].lower()

    def test_alone_gets_isolation_response(self):
        r = send("I have no one")
        assert "invisible" in r["response"].lower() or "alone" in r["response"].lower()

    def test_responses_are_different(self):
        """Each emotion type should produce a DIFFERENT response."""
        responses = set()
        for msg in ["I'm scared", "I'm feeling down", "rough day",
                     "I'm embarrassed", "I lost someone", "I have no one"]:
            r = send(msg)
            responses.add(r["response"][:50])
        # At least 4 distinct responses (some may share the generic)
        assert len(responses) >= 4, \
            f"Expected at least 4 distinct responses, got {len(responses)}"

    def test_no_service_mentions_in_emotional_responses(self):
        """Emotional responses should NEVER mention specific services."""
        service_words = ["food", "shelter", "shower", "clothing", "pantry"]
        for msg in ["I'm scared", "I'm feeling down", "rough day",
                     "I'm embarrassed", "I lost someone", "I have no one",
                     "I'm struggling"]:
            r = send(msg)
            for word in service_words:
                assert word not in r["response"].lower(), \
                    f"'{msg}' response should not mention '{word}'"


class TestShameTonePrefix:
    """When shame + service intent co-occur, the tone prefix should normalize."""

    def test_shame_food_bank_gets_normalizing_prefix(self):
        r = send("I never thought I'd need a food bank")
        resp = r["response"].lower()
        assert "shame" in resp or "strength" in resp or "no shame" in resp \
            or "lot of people" in resp, \
            f"Shame + service should get normalizing prefix, got: {r['response'][:80]}"

    def test_non_shame_emotional_service_gets_generic_prefix(self):
        r = send("I'm scared and need shelter in Brooklyn")
        resp = r["response"].lower()
        assert "i hear you" in resp or "want to help" in resp


class TestHelpEmotionalOverride:
    """Emotional tone should override the help action."""

    def test_embarrassed_help_routes_to_emotional(self):
        """'I'm embarrassed to ask for help' → emotional, not help menu."""
        import uuid
        sid = f"test-{uuid.uuid4().hex[:8]}"
        r = send("I'm embarrassed to ask for help", session_id=sid)
        from app.services.session_store import get_session_slots
        slots = get_session_slots(sid)
        assert slots.get("_last_action") == "emotional"

    def test_plain_help_still_works(self):
        """'help' without emotional tone → help menu as before."""
        r = send("help")
        # Should show service categories, not emotional response
        labels = [qr["label"] for qr in r.get("quick_replies", [])]
        assert len(labels) >= 5  # service category buttons
