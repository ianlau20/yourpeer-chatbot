"""
Tests for the LLM-based slot extractor.

Unit tests mock the Anthropic API. Integration tests (marked with _live suffix)
require ANTHROPIC_API_KEY in the environment and hit the real API.

Run unit tests:  python tests/test_llm_slot_extractor.py
Run live tests:  ANTHROPIC_API_KEY=sk-... python tests/test_llm_slot_extractor.py --live
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.llm_slot_extractor import (
    extract_slots_llm,
    extract_slots_smart,
    _empty_slots,
)


# -----------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------

def _mock_tool_response(**slots):
    """Build a mock Anthropic API response with tool_use output."""
    mock_block = MagicMock()
    mock_block.type = "tool_use"
    mock_block.name = "extract_intake_slots"
    mock_block.input = slots

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    return mock_response


def _mock_client_with_response(**slots):
    """Create a mock Anthropic client that returns the given slots."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_tool_response(**slots)
    return mock_client


# -----------------------------------------------------------------------
# UNIT TESTS — LLM EXTRACTION (mocked)
# -----------------------------------------------------------------------

@patch("app.services.llm_slot_extractor._get_client")
def test_llm_extracts_service_and_location(mock_get_client):
    """LLM should extract service type and location."""
    mock_get_client.return_value = _mock_client_with_response(
        service_type="food",
        location="Brooklyn",
    )
    result = extract_slots_llm("I need food in Brooklyn")
    assert result["service_type"] == "food"
    assert result["location"] == "Brooklyn"
    print("  PASS: LLM extracts service + location")


@patch("app.services.llm_slot_extractor._get_client")
def test_llm_extracts_age_and_gender(mock_get_client):
    """LLM should extract age and gender when mentioned."""
    mock_get_client.return_value = _mock_client_with_response(
        service_type="shelter",
        location="Queens",
        age=17,
        gender="female",
        urgency="high",
    )
    result = extract_slots_llm("I'm a 17 year old girl and I need shelter tonight in Queens")
    assert result["age"] == 17
    assert result["gender"] == "female"
    assert result["urgency"] == "high"
    print("  PASS: LLM extracts age, gender, urgency")


@patch("app.services.llm_slot_extractor._get_client")
def test_llm_handles_third_person(mock_get_client):
    """LLM should extract info about a third person ('my son is 12')."""
    mock_get_client.return_value = _mock_client_with_response(
        service_type="clothing",
        age=12,
    )
    result = extract_slots_llm("my son is 12 and needs a coat")
    assert result["service_type"] == "clothing"
    assert result["age"] == 12
    print("  PASS: LLM handles third-person requests")


@patch("app.services.llm_slot_extractor._get_client")
def test_llm_handles_contradicting_locations(mock_get_client):
    """LLM should pick the intended location, not the current one."""
    mock_get_client.return_value = _mock_client_with_response(
        service_type="food",
        location="Bronx",
    )
    result = extract_slots_llm("I'm in Queens but looking for food in the Bronx")
    assert result["location"] == "Bronx"
    print("  PASS: LLM picks intended location over current")


@patch("app.services.llm_slot_extractor._get_client")
def test_llm_handles_empty_message(mock_get_client):
    """LLM should return empty slots for non-service messages."""
    mock_get_client.return_value = _mock_client_with_response()
    result = extract_slots_llm("hello")
    assert result["service_type"] is None
    assert result["location"] is None
    print("  PASS: LLM returns empty for non-service messages")


@patch("app.services.llm_slot_extractor._get_client")
def test_llm_failure_returns_empty(mock_get_client):
    """If the LLM call fails, should return empty slots, not crash."""
    mock_get_client.side_effect = RuntimeError("API key missing")
    result = extract_slots_llm("I need food in Brooklyn")
    assert result == _empty_slots()
    print("  PASS: LLM failure returns empty slots")


# -----------------------------------------------------------------------
# UNIT TESTS — SMART EXTRACTOR (complexity-based routing)
# -----------------------------------------------------------------------

@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_uses_regex_for_simple_messages(mock_llm):
    """Short, clear messages with known location should skip LLM."""
    result = extract_slots_smart("I need food in Brooklyn")
    mock_llm.assert_not_called()
    assert result["service_type"] == "food"
    assert "brooklyn" in result["location"].lower()
    print("  PASS: simple message skips LLM")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_uses_llm_for_long_messages(mock_llm):
    """Long messages should always go to LLM even if regex finds slots."""
    mock_llm.return_value = {
        "service_type": "shelter",
        "location": "East New York",
        "age": None,
        "urgency": "high",
        "gender": None,
    }
    msg = (
        "I just got out of the hospital and I have been staying with friends "
        "in East New York but they can not keep me anymore"
    )
    result = extract_slots_smart(msg)
    mock_llm.assert_called_once()
    assert result["service_type"] == "shelter"  # LLM gets this right
    assert "east new york" in result["location"].lower()
    print("  PASS: long message goes to LLM")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_uses_llm_when_regex_partial(mock_llm):
    """When regex finds service but no location, LLM should be called."""
    mock_llm.return_value = {
        "service_type": "food",
        "location": "Harlem",
        "age": None,
        "urgency": None,
        "gender": None,
    }
    result = extract_slots_smart("I need food")
    mock_llm.assert_called_once()
    print("  PASS: partial regex triggers LLM")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_uses_llm_for_implicit_needs(mock_llm):
    """Implicit needs that regex can't parse should trigger LLM."""
    mock_llm.return_value = {
        "service_type": "shelter",
        "location": "Bronx",
        "age": None,
        "urgency": "high",
        "gender": "female",
    }
    result = extract_slots_smart("somewhere safe for tonight, I'm a woman near the Bronx")
    mock_llm.assert_called_once()
    assert result["service_type"] == "shelter"
    assert result["urgency"] == "high"
    assert result["gender"] == "female"
    print("  PASS: implicit needs go to LLM")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_llm_supplements_with_regex(mock_llm):
    """When LLM misses a slot that regex got, regex fills the gap."""
    # LLM gets service+location but misses urgency
    mock_llm.return_value = {
        "service_type": "food",
        "location": "Harlem",
        "age": None,
        "urgency": None,  # LLM missed this
        "gender": None,
    }
    # "tonight" would be caught by regex urgency extraction
    result = extract_slots_smart("I need food tonight in Harlem please help me out")
    assert result["service_type"] == "food"
    assert result["location"] == "Harlem"
    # Regex urgency should supplement the LLM gap
    assert result["urgency"] == "high"
    print("  PASS: regex supplements LLM gaps")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_llm_failure_falls_back_to_regex(mock_llm):
    """If LLM fails, smart extractor should return regex results."""
    mock_llm.return_value = _empty_slots()  # LLM failed
    result = extract_slots_smart("I need food")
    assert result["service_type"] == "food"  # regex still works
    print("  PASS: LLM failure falls back to regex")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_conflicting_keywords_go_to_llm(mock_llm):
    """Messages with multiple service keywords should go to LLM."""
    mock_llm.return_value = {
        "service_type": "shelter",
        "location": "Manhattan",
        "age": None,
        "urgency": None,
        "gender": None,
    }
    # "hospital" (medical) + "shelter" — conflicting keywords
    result = extract_slots_smart("hospital near Manhattan for shelter")
    mock_llm.assert_called_once()
    print("  PASS: conflicting keywords go to LLM")


@patch("app.services.llm_slot_extractor.extract_slots_llm")
def test_smart_unknown_location_goes_to_llm(mock_llm):
    """Unknown location (not in known list) should go to LLM."""
    mock_llm.return_value = {
        "service_type": "food",
        "location": "City Hall",
        "age": None,
        "urgency": None,
        "gender": None,
    }
    result = extract_slots_smart("food near City Hall")
    mock_llm.assert_called_once()
    print("  PASS: unknown location goes to LLM")
    assert result["service_type"] == "food"  # regex still got this
    print("  PASS: LLM failure falls back to regex")


# -----------------------------------------------------------------------
# INTEGRATION TESTS (only run with --live flag)
# -----------------------------------------------------------------------

_skip_no_api_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live LLM tests",
)


@_skip_no_api_key
def test_live_simple_extraction():
    """[LIVE] Simple service + location extraction."""
    result = extract_slots_llm("I need food in Brooklyn")
    assert result["service_type"] == "food"
    assert "brooklyn" in (result["location"] or "").lower()
    print("  PASS [LIVE]: simple extraction")


@_skip_no_api_key
def test_live_third_person():
    """[LIVE] Third-person extraction."""
    result = extract_slots_llm("my son is 12 and needs a warm coat")
    assert result["service_type"] == "clothing"
    assert result["age"] == 12
    print("  PASS [LIVE]: third-person extraction")


@_skip_no_api_key
def test_live_contradicting_locations():
    """[LIVE] Intended vs current location."""
    result = extract_slots_llm("I'm in Queens but looking for food in the Bronx")
    assert result["service_type"] == "food"
    assert "bronx" in (result["location"] or "").lower()
    print("  PASS [LIVE]: contradicting locations")


@_skip_no_api_key
def test_live_implicit_needs():
    """[LIVE] Implicit service type from context."""
    result = extract_slots_llm("somewhere safe for tonight, I'm a woman")
    assert result["service_type"] == "shelter"
    assert result["urgency"] == "high"
    assert result["gender"] is not None
    print("  PASS [LIVE]: implicit needs")


@_skip_no_api_key
def test_live_complex_sentence():
    """[LIVE] Complex sentence with multiple slots."""
    result = extract_slots_llm(
        "I'm 22, just got out of Rikers, and I need help finding "
        "a place to stay in the Bronx tonight"
    )
    assert result["service_type"] == "shelter"
    assert result["age"] == 22
    assert "bronx" in (result["location"] or "").lower()
    assert result["urgency"] == "high"
    print("  PASS [LIVE]: complex sentence")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    run_live = "--live" in sys.argv

    print("\nLLM Slot Extractor Tests\n" + "=" * 50)

    print("\n--- LLM Extraction (mocked) ---")
    test_llm_extracts_service_and_location()
    test_llm_extracts_age_and_gender()
    test_llm_handles_third_person()
    test_llm_handles_contradicting_locations()
    test_llm_handles_empty_message()
    test_llm_failure_returns_empty()

    print("\n--- Smart Extractor (complexity routing) ---")
    test_smart_uses_regex_for_simple_messages()
    test_smart_uses_llm_for_long_messages()
    test_smart_uses_llm_when_regex_partial()
    test_smart_uses_llm_for_implicit_needs()
    test_smart_llm_supplements_with_regex()
    test_smart_llm_failure_falls_back_to_regex()
    test_smart_conflicting_keywords_go_to_llm()
    test_smart_unknown_location_goes_to_llm()

    if run_live:
        print("\n--- Integration Tests (LIVE API) ---")
        test_live_simple_extraction()
        test_live_third_person()
        test_live_contradicting_locations()
        test_live_implicit_needs()
        test_live_complex_sentence()
    else:
        print("\n--- Integration Tests: SKIPPED (run with --live) ---")

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
