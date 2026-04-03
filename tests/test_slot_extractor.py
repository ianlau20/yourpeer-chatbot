"""
Tests for the slot extractor.

Run with: python -m pytest tests/test_slot_extractor.py -v
Or just:  python tests/test_slot_extractor.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.slot_extractor import (
    extract_slots,
    merge_slots,
    is_enough_to_answer,
    next_follow_up_question,
    NEAR_ME_SENTINEL,
)


# -----------------------------------------------------------------------
# SERVICE TYPE EXTRACTION
# -----------------------------------------------------------------------

def test_food_keywords():
    """All food-related phrases should extract service_type=food."""
    phrases = [
        "I need food",
        "Where can I get a meal?",
        "I'm hungry",
        "Is there a food bank nearby?",
        "Looking for a soup kitchen",
        "Free food in Brooklyn",
        "I need groceries",
        "Any food pantry open today?",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "food", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: food keywords")


def test_shelter_keywords():
    """All shelter-related phrases should extract service_type=shelter."""
    phrases = [
        "I need shelter",
        "I need a place to stay",
        "Where can I sleep tonight?",
        "I'm homeless and need a bed",
        "Looking for housing",
        "Is there a drop-in center?",
        "I need somewhere to sleep",
        "Warming center in Manhattan",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "shelter", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: shelter keywords")


def test_clothing_keywords():
    """Clothing-related phrases should extract service_type=clothing."""
    phrases = [
        "I need clothes",
        "Where can I get a jacket?",
        "Free clothing near me",
        "I need a coat",
        "Can I get shoes somewhere?",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "clothing", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: clothing keywords")


def test_personal_care_keywords():
    """Shower/hygiene phrases should extract service_type=personal_care."""
    phrases = [
        "I need a shower",
        "Where can I do laundry?",
        "I need toiletries",
        "Is there a place to clean up?",
        "I need a haircut",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "personal_care", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: personal care keywords")


def test_medical_keywords():
    """Medical phrases should extract service_type=medical."""
    phrases = [
        "I need to see a doctor",
        "Is there a clinic nearby?",
        "I need medical help",
        "Where's the nearest hospital?",
        "I need a dentist",
        "I need health care",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "medical", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: medical keywords")


def test_mental_health_keywords():
    """Mental health phrases should extract service_type=mental_health."""
    phrases = [
        "I need mental health help",
        "I'm looking for counseling",
        "I need a therapist",
        "Where can I find a support group?",
        "I'm dealing with addiction",
        "I need help with substance abuse",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "mental_health", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: mental health keywords")


def test_legal_keywords():
    """Legal phrases should extract service_type=legal."""
    phrases = [
        "I need legal help",
        "I'm facing eviction",
        "I need an immigration lawyer",
        "Can I get legal aid?",
        "I need help with my green card",
        "I need a public defender",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "legal", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: legal keywords")


def test_employment_keywords():
    """Employment phrases should extract service_type=employment."""
    phrases = [
        "I need a job",
        "Where can I find work?",
        "Job training programs",
        "Help with my resume",
        "I need job placement",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "employment", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: employment keywords")


def test_other_keywords():
    """Benefits/ID/misc phrases should extract service_type=other."""
    phrases = [
        "How do I get SNAP benefits?",
        "I need help with food stamps",
        "I need an ID",
        "I need a birth certificate",
        "Is there free wifi anywhere?",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] == "other", f"Failed on: {phrase} → {slots['service_type']}"
    print("  PASS: other service keywords")


def test_no_service_type():
    """Messages without service keywords should return None."""
    phrases = [
        "Hello",
        "Thank you",
        "What time is it?",
        "Tell me more",
        "Yes",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["service_type"] is None, f"False positive on: {phrase} → {slots['service_type']}"
    print("  PASS: no false positive service types")


# -----------------------------------------------------------------------
# LOCATION EXTRACTION
# -----------------------------------------------------------------------

def test_location_in_pattern():
    """'in <location>' pattern should extract the location."""
    cases = [
        ("food in Brooklyn", "brooklyn"),
        ("shelter in Queens", "queens"),
        ("I'm in Manhattan", "manhattan"),
        ("services in the Bronx", "bronx"),
    ]
    for phrase, expected in cases:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location found in: {phrase}"
        assert expected.lower() in slots["location"].lower(), \
            f"Expected '{expected}' in location for: {phrase} → {slots['location']}"
    print("  PASS: 'in <location>' pattern")


def test_location_preposition_variants():
    """Prepositions like 'near', 'around', 'by', 'from' should extract location."""
    cases = [
        ("actually near Queens", "queens"),
        ("food around Harlem", "harlem"),
        ("shelter by Midtown", "midtown"),
        ("I'm from Brooklyn", "brooklyn"),
        ("services near the Bronx", "bronx"),
    ]
    for phrase, expected in cases:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location found in: {phrase}"
        assert expected.lower() in slots["location"].lower(), \
            f"Expected '{expected}' in location for: {phrase} → {slots['location']}"
    print("  PASS: preposition variants (near/around/by/from)")


def test_location_known_names():
    """Known NYC borough/neighborhood names should be extracted."""
    cases = [
        ("food brooklyn", "brooklyn"),
        ("shelter queens tonight", "queens"),
        ("midtown clinic", "midtown"),
        ("harlem food pantry", "harlem"),
        ("long island city shelter", "long island city"),
    ]
    for phrase, expected in cases:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location found in: {phrase}"
        assert expected in slots["location"].lower(), \
            f"Expected '{expected}' in location for: {phrase} → {slots['location']}"
    print("  PASS: known NYC location names")


def test_location_false_positives():
    """Phrases like 'in need' or 'in trouble' should NOT extract a location."""
    phrases = [
        "I'm in need of help",
        "I'm in trouble",
        "I'm in a bad situation",
        "I'm in danger",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["location"] is None, \
            f"False positive location in: {phrase} → {slots['location']}"
    print("  PASS: no false positive locations")


def test_near_me_detection():
    """'Near me' phrases should return the sentinel, not a real location."""
    phrases = [
        "food near me",
        "shelters nearby",
        "closest food bank",
        "services close to me",
        "food around here",
        "what's in my area",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["location"] == NEAR_ME_SENTINEL, \
            f"Expected NEAR_ME_SENTINEL for: {phrase} → {slots['location']}"
    print("  PASS: near me detection")


def test_no_location():
    """Messages without location info should return None."""
    phrases = [
        "I need food",
        "Help me find a shelter",
        "Where can I get clothes?",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["location"] is None, \
            f"False positive location in: {phrase} → {slots['location']}"
    print("  PASS: no false positive locations on clean messages")


# -----------------------------------------------------------------------
# AGE EXTRACTION
# -----------------------------------------------------------------------

def test_age_extraction():
    """Various age patterns should be extracted correctly."""
    cases = [
        ("I am 17", 17),
        ("I'm 22", 22),
        ("age 30", 30),
        ("I'm 65 years old", 65),
        ("im 19", 19),
    ]
    for phrase, expected in cases:
        slots = extract_slots(phrase)
        assert slots["age"] == expected, \
            f"Expected age {expected} for: {phrase} → {slots['age']}"
    print("  PASS: age extraction")


def test_no_age():
    """Messages without age info should return None."""
    phrases = [
        "I need food in Brooklyn",
        "Help me find shelter",
        "Looking for a job",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["age"] is None, \
            f"False positive age in: {phrase} → {slots['age']}"
    print("  PASS: no false positive ages")


def test_age_out_of_range():
    """Ages outside 1-119 should be rejected."""
    phrases = [
        "I am 0",
        "I am 150",
        "age 999",
    ]
    for phrase in phrases:
        slots = extract_slots(phrase)
        assert slots["age"] is None, \
            f"Should reject out-of-range age in: {phrase} → {slots['age']}"
    print("  PASS: out-of-range ages rejected")


# -----------------------------------------------------------------------
# URGENCY EXTRACTION
# -----------------------------------------------------------------------

def test_urgency_extraction():
    """Urgency keywords should be classified correctly."""
    high_phrases = [
        ("I need shelter tonight", "high"),
        ("This is urgent", "high"),
        ("I need food right now", "high"),
        ("Help me asap", "high"),
    ]
    for phrase, expected in high_phrases:
        slots = extract_slots(phrase)
        assert slots["urgency"] == expected, \
            f"Expected urgency '{expected}' for: {phrase} → {slots['urgency']}"

    medium_phrases = [
        ("I need help soon", "medium"),
        ("Sometime this week", "medium"),
    ]
    for phrase, expected in medium_phrases:
        slots = extract_slots(phrase)
        assert slots["urgency"] == expected, \
            f"Expected urgency '{expected}' for: {phrase} → {slots['urgency']}"
    print("  PASS: urgency extraction")


def test_no_urgency():
    """Messages without urgency keywords should return None."""
    slots = extract_slots("I need food in Brooklyn")
    assert slots["urgency"] is None
    print("  PASS: no false positive urgency")


# -----------------------------------------------------------------------
# MULTI-SLOT EXTRACTION
# -----------------------------------------------------------------------

def test_multi_slot_single_message():
    """A single message can fill multiple slots at once."""
    slots = extract_slots("I need shelter in Queens tonight, I'm 17")
    assert slots["service_type"] == "shelter"
    assert "queens" in (slots["location"] or "").lower()
    assert slots["urgency"] == "high"
    assert slots["age"] == 17
    print("  PASS: multi-slot extraction from one message")


def test_full_sentence():
    """Realistic full sentences should extract correctly."""
    slots = extract_slots("I'm 22 and I need food in Brooklyn")
    assert slots["service_type"] == "food"
    assert "brooklyn" in (slots["location"] or "").lower()
    assert slots["age"] == 22
    print("  PASS: full sentence extraction")


# -----------------------------------------------------------------------
# MERGE SLOTS
# -----------------------------------------------------------------------

def test_merge_new_over_empty():
    """New slots should merge into an empty session."""
    existing = {}
    new = {"service_type": "food", "location": None, "urgency": None, "age": None}
    merged = merge_slots(existing, new)
    assert merged["service_type"] == "food"
    assert "location" not in merged or merged.get("location") is None
    print("  PASS: merge new over empty")


def test_merge_preserves_existing():
    """Existing slots should be preserved when new values are None."""
    existing = {"service_type": "food", "location": "Brooklyn"}
    new = {"service_type": None, "location": None, "urgency": "high", "age": None}
    merged = merge_slots(existing, new)
    assert merged["service_type"] == "food"
    assert merged["location"] == "Brooklyn"
    assert merged["urgency"] == "high"
    print("  PASS: merge preserves existing")


def test_merge_overrides_with_new():
    """New non-None values should override existing ones."""
    existing = {"service_type": "food", "location": "Brooklyn"}
    new = {"service_type": "shelter", "location": None, "urgency": None, "age": None}
    merged = merge_slots(existing, new)
    assert merged["service_type"] == "shelter"
    assert merged["location"] == "Brooklyn"
    print("  PASS: merge overrides with new values")


def test_merge_near_me_doesnt_override_real_location():
    """A 'near me' sentinel should NOT replace an existing real location."""
    existing = {"location": "Brooklyn"}
    new = {"location": NEAR_ME_SENTINEL}
    merged = merge_slots(existing, new)
    assert merged["location"] == "Brooklyn"
    print("  PASS: near me doesn't override real location")


def test_merge_real_location_replaces_near_me():
    """A real location should replace a previous 'near me' sentinel."""
    existing = {"location": NEAR_ME_SENTINEL}
    new = {"location": "Queens"}
    merged = merge_slots(existing, new)
    assert merged["location"] == "Queens"
    print("  PASS: real location replaces near me")


# -----------------------------------------------------------------------
# IS ENOUGH TO ANSWER
# -----------------------------------------------------------------------

def test_enough_with_service_and_location():
    """Should be enough when both service_type and location are present."""
    assert is_enough_to_answer({"service_type": "food", "location": "Brooklyn"}) is True
    print("  PASS: enough with service + location")


def test_not_enough_missing_service():
    """Should NOT be enough when service_type is missing."""
    assert is_enough_to_answer({"location": "Brooklyn"}) is False
    print("  PASS: not enough without service type")


def test_not_enough_missing_location():
    """Should NOT be enough when location is missing."""
    assert is_enough_to_answer({"service_type": "food"}) is False
    print("  PASS: not enough without location")


def test_not_enough_near_me_sentinel():
    """The 'near me' sentinel should NOT count as a real location."""
    assert is_enough_to_answer({
        "service_type": "food",
        "location": NEAR_ME_SENTINEL,
    }) is False
    print("  PASS: near me sentinel not enough")


def test_not_enough_empty():
    """Empty slots should not be enough."""
    assert is_enough_to_answer({}) is False
    print("  PASS: empty slots not enough")


# -----------------------------------------------------------------------
# FOLLOW-UP QUESTIONS
# -----------------------------------------------------------------------

def test_followup_asks_service_type_first():
    """With no slots, should ask about service type."""
    question = next_follow_up_question({})
    assert "help" in question.lower() or "need" in question.lower()
    print("  PASS: asks service type first")


def test_followup_asks_location_second():
    """With service type but no location, should ask about location."""
    question = next_follow_up_question({"service_type": "food"})
    assert "borough" in question.lower() or "neighborhood" in question.lower() or "area" in question.lower()
    print("  PASS: asks location second")


def test_followup_asks_location_for_near_me():
    """With 'near me' as location, should still ask for real location."""
    question = next_follow_up_question({
        "service_type": "food",
        "location": NEAR_ME_SENTINEL,
    })
    assert "borough" in question.lower() or "neighborhood" in question.lower()
    print("  PASS: asks real location when near me")


def test_followup_asks_age_for_shelter():
    """For shelter with location but no age, should ask about age."""
    question = next_follow_up_question({
        "service_type": "shelter",
        "location": "Brooklyn",
    })
    assert "age" in question.lower()
    print("  PASS: asks age for shelter")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nSlot Extractor Tests\n" + "=" * 50)

    print("\n--- Service Type Extraction ---")
    test_food_keywords()
    test_shelter_keywords()
    test_clothing_keywords()
    test_personal_care_keywords()
    test_medical_keywords()
    test_mental_health_keywords()
    test_legal_keywords()
    test_employment_keywords()
    test_other_keywords()
    test_no_service_type()

    print("\n--- Location Extraction ---")
    test_location_in_pattern()
    test_location_preposition_variants()
    test_location_known_names()
    test_location_false_positives()
    test_near_me_detection()
    test_no_location()

    print("\n--- Age Extraction ---")
    test_age_extraction()
    test_no_age()
    test_age_out_of_range()

    print("\n--- Urgency Extraction ---")
    test_urgency_extraction()
    test_no_urgency()

    print("\n--- Multi-Slot Extraction ---")
    test_multi_slot_single_message()
    test_full_sentence()

    print("\n--- Merge Slots ---")
    test_merge_new_over_empty()
    test_merge_preserves_existing()
    test_merge_overrides_with_new()
    test_merge_near_me_doesnt_override_real_location()
    test_merge_real_location_replaces_near_me()

    print("\n--- Is Enough To Answer ---")
    test_enough_with_service_and_location()
    test_not_enough_missing_service()
    test_not_enough_missing_location()
    test_not_enough_near_me_sentinel()
    test_not_enough_empty()

    print("\n--- Follow-Up Questions ---")
    test_followup_asks_service_type_first()
    test_followup_asks_location_second()
    test_followup_asks_location_for_near_me()
    test_followup_asks_age_for_shelter()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
