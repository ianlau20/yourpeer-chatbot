"""
Tests for crisis detection — validates that crisis language is detected
across all five categories and that non-crisis messages pass through.

Run with: python -m pytest tests/test_crisis_detector.py -v
Or just:  python tests/test_crisis_detector.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.crisis_detector import detect_crisis, is_crisis


# -----------------------------------------------------------------------
# SUICIDE / SELF-HARM
# -----------------------------------------------------------------------

def test_suicide_direct_statements():
    """Direct suicidal statements should be detected."""
    phrases = [
        "I want to kill myself",
        "I wanna die",
        "I wish I was dead",
        "I'm better off dead",
        "I want to end my life",
        "I don't want to live anymore",
        "There's no reason to live",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "suicide_self_harm", \
            f"Wrong category for '{phrase}': {result[0]}"
    print("  PASS: suicide direct statements")


def test_self_harm():
    """Self-harm language should be detected."""
    phrases = [
        "I've been cutting myself",
        "I keep hurting myself",
        "I'm harming myself",
        "self harm",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "suicide_self_harm"
    print("  PASS: self-harm detection")


def test_suicide_response_has_988():
    """Suicide response must include 988 lifeline."""
    result = detect_crisis("I want to kill myself")
    assert result is not None
    assert "988" in result[1]
    assert "741741" in result[1]  # Crisis Text Line
    print("  PASS: suicide response includes 988 + Crisis Text Line")


def test_suicide_response_has_trevor():
    """Suicide response must include Trevor Project for LGBTQ+ youth."""
    result = detect_crisis("I want to die")
    assert "Trevor" in result[1]
    print("  PASS: suicide response includes Trevor Project")


# -----------------------------------------------------------------------
# VIOLENCE / HARM TO OTHERS
# -----------------------------------------------------------------------

def test_violence_threats():
    """Threats of violence should be detected."""
    phrases = [
        "I'm going to kill someone",
        "I want to hurt someone",
        "I'm gonna hurt him",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "violence", \
            f"Wrong category for '{phrase}': {result[0]}"
    print("  PASS: violence threats")


def test_violence_response_has_911():
    """Violence response must include 911."""
    result = detect_crisis("I'm going to hurt someone")
    assert "911" in result[1]
    print("  PASS: violence response includes 911")


# -----------------------------------------------------------------------
# DOMESTIC VIOLENCE / ABUSE
# -----------------------------------------------------------------------

def test_domestic_violence():
    """Domestic violence language should be detected."""
    phrases = [
        "My partner hits me",
        "I'm being abused",
        "I'm in an abusive relationship",
        "domestic violence",
        "he beats me",
        "I'm afraid to go home",
        "my boyfriend hits me",
        "I need a restraining order",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "domestic_violence", \
            f"Wrong category for '{phrase}': {result[0]}"
    print("  PASS: domestic violence detection")


def test_dv_response_has_hotline():
    """DV response must include the National DV Hotline."""
    result = detect_crisis("my partner hits me")
    assert "1-800-799-7233" in result[1]
    print("  PASS: DV response includes National DV Hotline")


def test_dv_response_has_nyc_hotline():
    """DV response should include the NYC-specific hotline."""
    result = detect_crisis("domestic violence")
    assert "1-800-621-4673" in result[1]
    print("  PASS: DV response includes NYC DV Hotline")


# -----------------------------------------------------------------------
# TRAFFICKING / EXPLOITATION
# -----------------------------------------------------------------------

def test_trafficking():
    """Trafficking language should be detected."""
    phrases = [
        "I'm being trafficked",
        "they forced me into prostitution",
        "they took my passport",
        "I can't leave my job, they won't let me",
        "I'm being held against my will",
        "human trafficking",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "trafficking", \
            f"Wrong category for '{phrase}': {result[0]}"
    print("  PASS: trafficking detection")


def test_trafficking_response_has_hotline():
    """Trafficking response must include National Trafficking Hotline."""
    result = detect_crisis("I'm being trafficked")
    assert "1-888-373-7888" in result[1]
    assert "233733" in result[1]  # BeFree text number
    print("  PASS: trafficking response includes hotline")


# -----------------------------------------------------------------------
# MEDICAL EMERGENCY
# -----------------------------------------------------------------------

def test_medical_emergency():
    """Medical emergency language should be detected."""
    phrases = [
        "I'm having a heart attack",
        "I can't breathe",
        "someone is overdosing",
        "they're not breathing",
        "there's blood everywhere",
        "having a seizure",
    ]
    for phrase in phrases:
        result = detect_crisis(phrase)
        assert result is not None, f"Missed crisis: '{phrase}'"
        assert result[0] == "medical_emergency", \
            f"Wrong category for '{phrase}': {result[0]}"
    print("  PASS: medical emergency detection")


def test_medical_response_has_911():
    """Medical emergency response must include 911."""
    result = detect_crisis("I can't breathe")
    assert "911" in result[1]
    print("  PASS: medical response includes 911")


def test_medical_response_has_poison_control():
    """Medical emergency response should include Poison Control."""
    result = detect_crisis("someone is overdosing")
    assert "1-800-222-1222" in result[1]
    print("  PASS: medical response includes Poison Control")


# -----------------------------------------------------------------------
# NO FALSE POSITIVES
# -----------------------------------------------------------------------

def test_no_false_positives_service_requests():
    """Normal service requests should NOT trigger crisis detection."""
    safe_messages = [
        "I need food in Brooklyn",
        "Where can I find shelter tonight?",
        "I'm looking for a job",
        "I need legal help",
        "I need medical help",
        "I'm hungry",
        "I need clothes",
        "Where's the nearest clinic?",
        "I need help with my resume",
    ]
    for msg in safe_messages:
        result = detect_crisis(msg)
        assert result is None, \
            f"False positive on: '{msg}' → {result[0] if result else None}"
    print("  PASS: no false positives on service requests")


def test_no_false_positives_conversational():
    """Conversational messages should NOT trigger crisis detection."""
    safe_messages = [
        "thank you",
        "hi",
        "start over",
        "tell me more",
        "that's helpful",
        "I'm doing okay",
        "I'm fine",
        "what can you do",
    ]
    for msg in safe_messages:
        result = detect_crisis(msg)
        assert result is None, \
            f"False positive on: '{msg}' → {result[0] if result else None}"
    print("  PASS: no false positives on conversational messages")


def test_no_false_positive_on_hurt_in_context():
    """'Hurt' in a non-crisis context should not trigger."""
    # "My foot hurts" shouldn't trigger violence detection
    safe_messages = [
        "My foot hurts",
        "I hurt my back at work",
        "The process hurt my application",
    ]
    for msg in safe_messages:
        result = detect_crisis(msg)
        assert result is None, \
            f"False positive on: '{msg}' → {result[0] if result else None}"
    print("  PASS: 'hurt' in non-crisis context doesn't trigger")


# -----------------------------------------------------------------------
# PRIORITY / INTEGRATION
# -----------------------------------------------------------------------

def test_is_crisis_helper():
    """is_crisis() should return True/False correctly."""
    assert is_crisis("I want to kill myself") is True
    assert is_crisis("I need food in Brooklyn") is False
    print("  PASS: is_crisis helper")


def test_crisis_in_longer_message():
    """Crisis language embedded in a longer message should still be detected."""
    msg = "I've been homeless for a month and I just want to die"
    result = detect_crisis(msg)
    assert result is not None
    assert result[0] == "suicide_self_harm"
    print("  PASS: crisis detected in longer message")


def test_crisis_with_service_request():
    """Crisis language mixed with a service request should still detect crisis."""
    msg = "I need shelter and I'm being abused by my partner"
    result = detect_crisis(msg)
    assert result is not None
    assert result[0] == "domestic_violence"
    print("  PASS: crisis detected alongside service request")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nCrisis Detector Tests\n" + "=" * 50)

    print("\n--- Suicide / Self-Harm ---")
    test_suicide_direct_statements()
    test_self_harm()
    test_suicide_response_has_988()
    test_suicide_response_has_trevor()

    print("\n--- Violence ---")
    test_violence_threats()
    test_violence_response_has_911()

    print("\n--- Domestic Violence ---")
    test_domestic_violence()
    test_dv_response_has_hotline()
    test_dv_response_has_nyc_hotline()

    print("\n--- Trafficking ---")
    test_trafficking()
    test_trafficking_response_has_hotline()

    print("\n--- Medical Emergency ---")
    test_medical_emergency()
    test_medical_response_has_911()
    test_medical_response_has_poison_control()

    print("\n--- No False Positives ---")
    test_no_false_positives_service_requests()
    test_no_false_positives_conversational()
    test_no_false_positive_on_hurt_in_context()

    print("\n--- Priority / Integration ---")
    test_is_crisis_helper()
    test_crisis_in_longer_message()
    test_crisis_with_service_request()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
