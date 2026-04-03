"""
Tests for the PII redaction pipeline.

Run with: python -m pytest tests/test_pii_redactor.py -v
Or just:  python tests/test_pii_redactor.py
"""

import sys
import os

# Add backend to path so imports work when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.privacy.pii_redactor import redact_pii, detect_pii, has_pii


def test_phone_numbers():
    """Various phone number formats should be redacted."""
    cases = [
        ("Call me at 212-555-1234", "Call me at [PHONE]"),
        ("My number is (718) 555-0199", "My number is [PHONE]"),
        ("Reach me at 917.555.4567", "Reach me at [PHONE]"),
        ("Text 2125551234 please", "Text [PHONE] please"),
        ("+1 212 555 1234", "[PHONE]"),
    ]
    for original, expected in cases:
        redacted, dets = redact_pii(original)
        assert "[PHONE]" in redacted, f"Failed to redact phone in: {original}"
        assert any(d.pii_type == "PHONE" for d in dets), f"No PHONE detection in: {original}"
    print("  PASS: phone numbers")


def test_ssn():
    """Social Security Numbers should be redacted."""
    cases = [
        ("My SSN is 123-45-6789", "[SSN]"),
        ("Social 123 45 6789", "[SSN]"),
    ]
    for original, expected_placeholder in cases:
        redacted, dets = redact_pii(original)
        assert expected_placeholder in redacted, f"Failed to redact SSN in: {original}"
        assert any(d.pii_type == "SSN" for d in dets), f"No SSN detection in: {original}"
    print("  PASS: SSN")


def test_email():
    """Email addresses should be redacted."""
    redacted, dets = redact_pii("Email me at john.doe@gmail.com")
    assert "[EMAIL]" in redacted
    assert "john.doe@gmail.com" not in redacted
    assert any(d.pii_type == "EMAIL" for d in dets)
    print("  PASS: email")


def test_dob():
    """Date of birth patterns should be redacted."""
    cases = [
        "I was born 01/15/1990",
        "DOB: 1-15-90",
        "Born on January 15, 1990",
        "Birthday is Jan 15 1990",
    ]
    for original in cases:
        redacted, dets = redact_pii(original)
        assert "[DOB]" in redacted, f"Failed to redact DOB in: {original}"
    print("  PASS: dates of birth")


def test_street_address():
    """Street addresses should be redacted."""
    cases = [
        "I live at 123 Main Street",
        "Come to 456 Broadway",
        "My address is 789 Flatbush Ave",
    ]
    for original in cases:
        redacted, dets = redact_pii(original)
        assert "[ADDRESS]" in redacted, f"Failed to redact address in: {original}"
    print("  PASS: street addresses")


def test_names():
    """Names introduced with common phrases should be redacted."""
    cases = [
        ("My name is John Smith", "[NAME]"),
        ("My name is Maria", "[NAME]"),
        ("Call me David", "[NAME]"),
    ]
    for original, expected in cases:
        redacted, dets = redact_pii(original)
        assert expected in redacted, f"Failed to redact name in: {original}"
    print("  PASS: names")


def test_no_false_positives_locations():
    """NYC locations should NOT be redacted as names."""
    safe_messages = [
        "I'm in Brooklyn",
        "I'm in Queens",
        "I'm in Manhattan looking for food",
        "I need shelter in Harlem",
        "Food in the Bronx",
    ]
    for msg in safe_messages:
        redacted, dets = redact_pii(msg)
        name_dets = [d for d in dets if d.pii_type == "NAME"]
        assert len(name_dets) == 0, f"False positive NAME in: {msg} → detected: {[d.original for d in name_dets]}"
    print("  PASS: no false positives on locations")


def test_no_false_positives_service_keywords():
    """Service-related words should NOT be redacted."""
    safe_messages = [
        "I'm hungry and need food",
        "I'm homeless and looking for shelter",
        "I'm looking for a job",
        "I need medical help",
    ]
    for msg in safe_messages:
        redacted, dets = redact_pii(msg)
        name_dets = [d for d in dets if d.pii_type == "NAME"]
        assert len(name_dets) == 0, f"False positive NAME in: {msg}"
    print("  PASS: no false positives on service keywords")


def test_multiple_pii():
    """Messages with multiple PII types should all be redacted."""
    msg = "My name is Sarah, my number is 212-555-9876, and my email is sarah@test.com"
    redacted, dets = redact_pii(msg)
    assert "[NAME]" in redacted
    assert "[PHONE]" in redacted
    assert "[EMAIL]" in redacted
    assert "Sarah" not in redacted
    assert "212-555-9876" not in redacted
    assert "sarah@test.com" not in redacted
    assert len(dets) == 3
    print("  PASS: multiple PII types")


def test_no_pii():
    """Clean messages should pass through unchanged."""
    clean_messages = [
        "I need food in Brooklyn",
        "Where can I find a shelter tonight?",
        "I'm 22 years old",
        "Looking for legal help",
        "Thank you",
    ]
    for msg in clean_messages:
        redacted, dets = redact_pii(msg)
        assert redacted == msg, f"Unexpected redaction in: {msg} → {redacted}"
        assert len(dets) == 0, f"Unexpected PII in clean message: {msg}"
    print("  PASS: clean messages unchanged")


def test_has_pii():
    """Quick check function should work."""
    assert has_pii("Call me at 212-555-1234") is True
    assert has_pii("I need food in Brooklyn") is False
    print("  PASS: has_pii check")


def test_numbered_street_addresses():
    """Bug 4: Addresses with ordinal street numbers should be redacted.

    Previously, '456 West 42nd Street' and '789 5th Avenue' were NOT
    redacted because the regex required [A-Z][a-z]+ for street name
    words, which doesn't match '42nd' or '5th'.
    """
    cases = [
        ("I live at 456 West 42nd Street", "[ADDRESS]"),
        ("meet me at 789 5th Avenue", "[ADDRESS]"),
        ("Im at 100 East 125th Street", "[ADDRESS]"),
        ("the office is at 200 W 34th Street", "[ADDRESS]"),
        # Original patterns should still work
        ("I live at 123 Main Street", "[ADDRESS]"),
        ("Come to 456 Broadway", "[ADDRESS]"),
        ("My address is 789 Flatbush Ave", "[ADDRESS]"),
    ]
    for original, expected_tag in cases:
        redacted, dets = redact_pii(original)
        assert expected_tag in redacted, \
            f"Failed to redact address in: '{original}' → '{redacted}'"
        assert any(d.pii_type == "ADDRESS" for d in dets), \
            f"No ADDRESS detection in: '{original}'"

    # Bare street names without house numbers should NOT be redacted
    # (they're likely referring to a neighborhood/landmark, not PII)
    safe_cases = [
        "I live near 42nd Street",
        "somewhere around 5th Avenue",
    ]
    for original in safe_cases:
        redacted, dets = redact_pii(original)
        assert "[ADDRESS]" not in redacted, \
            f"False positive: '{original}' should NOT be redacted as address"
    print("  PASS: numbered street addresses")


if __name__ == "__main__":
    print("\nPII Redactor Tests\n" + "=" * 40)
    test_phone_numbers()
    test_ssn()
    test_email()
    test_dob()
    test_street_address()
    test_names()
    test_no_false_positives_locations()
    test_no_false_positives_service_keywords()
    test_multiple_pii()
    test_no_pii()
    test_has_pii()
    test_numbered_street_addresses()
    print("\n" + "=" * 40)
    print("ALL TESTS PASSED")
