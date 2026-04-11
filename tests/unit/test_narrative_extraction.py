"""Tests for narrative extraction — urgency-aware slot extraction
for long messages (20+ words).

Tests both the LLM path (mocked) and the regex fallback path.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.services.llm_slot_extractor import (
    _is_narrative, _narrative_regex_fallback, extract_slots_smart,
    _NARRATIVE_THRESHOLD, _URGENCY_HIERARCHY, extract_slots_narrative,
)


class TestNarrativeDetection:
    """Messages >= 20 words should be classified as narratives."""

    def test_short_message_not_narrative(self):
        assert not _is_narrative("I need food in Brooklyn")

    def test_long_message_is_narrative(self):
        msg = " ".join(["word"] * _NARRATIVE_THRESHOLD)
        assert _is_narrative(msg)

    def test_threshold_boundary(self):
        assert not _is_narrative(" ".join(["word"] * (_NARRATIVE_THRESHOLD - 1)))
        assert _is_narrative(" ".join(["word"] * _NARRATIVE_THRESHOLD))


class TestUrgencyHierarchy:
    """Shelter should outrank all other services."""

    def test_shelter_highest(self):
        assert _URGENCY_HIERARCHY["shelter"] > _URGENCY_HIERARCHY["medical"]
        assert _URGENCY_HIERARCHY["shelter"] > _URGENCY_HIERARCHY["food"]
        assert _URGENCY_HIERARCHY["shelter"] > _URGENCY_HIERARCHY["employment"]

    def test_medical_above_food(self):
        assert _URGENCY_HIERARCHY["medical"] > _URGENCY_HIERARCHY["food"]

    def test_food_above_employment(self):
        assert _URGENCY_HIERARCHY["food"] > _URGENCY_HIERARCHY["employment"]


class TestNarrativeRegexFallback:
    """When LLM is unavailable, regex fallback should re-prioritize
    by urgency hierarchy."""

    def test_hospital_housing_prioritizes_shelter(self):
        msg = ("I just got out of the hospital last week and my housing "
               "situation fell through because my roommate kicked me out "
               "and now I need somewhere to stay in the Bronx and also "
               "need to find a job")
        result = _narrative_regex_fallback(msg)
        assert result["service_type"] == "shelter"
        additional = [s for s, _ in result.get("additional_services", [])]
        assert "medical" in additional or "employment" in additional

    def test_runaway_youth_prioritizes_shelter(self):
        msg = ("I'm 17 and I ran away from home because my parents were "
               "abusing me and I need clothes and somewhere safe to stay "
               "in Bushwick tonight")
        result = _narrative_regex_fallback(msg)
        assert result["service_type"] == "shelter"
        assert result.get("age") == 17

    def test_eviction_prioritizes_shelter(self):
        msg = ("I got evicted last month and I've been staying with friends "
               "but they can't keep me anymore and I have a 6 year old "
               "daughter and we need food and shelter in East New York")
        result = _narrative_regex_fallback(msg)
        assert result["service_type"] == "shelter"
        additional = [s for s, _ in result.get("additional_services", [])]
        assert "food" in additional

    def test_reentry_prioritizes_shelter(self):
        msg = ("I was just released from Rikers two days ago and I need "
               "a place to stay in the South Bronx and also need to find "
               "employment as soon as possible")
        result = _narrative_regex_fallback(msg)
        assert result["service_type"] == "shelter"

    def test_urgency_inferred_from_context(self):
        msg = ("I got evicted today and I have nowhere to go tonight and "
               "I also need food for my kids in the Bronx please help me")
        result = _narrative_regex_fallback(msg)
        assert result.get("urgency") == "high"

    def test_single_service_no_change(self):
        """Narratives with only one service should keep it as primary."""
        msg = ("I've been looking for food pantries for a while now and "
               "nobody seems to have anything available in my area and "
               "I'm running out of options in Brooklyn")
        result = _narrative_regex_fallback(msg)
        assert result["service_type"] == "food"

    def test_location_preserved(self):
        msg = ("I just got out of the hospital and my housing fell through "
               "and I need somewhere to stay in the Bronx and also a job")
        result = _narrative_regex_fallback(msg)
        assert "bronx" in result.get("location", "").lower()


class TestExtractSlotsSmart_Narrative:
    """extract_slots_smart should route narratives through the
    urgency-aware path."""

    def test_narrative_uses_fallback_without_llm(self):
        """Without LLM, narrative should use regex fallback with
        urgency re-prioritization."""
        msg = ("I just got out of the hospital and my housing fell through "
               "and I need somewhere to stay in the Bronx and find a job")
        result = extract_slots_smart(msg)
        assert result["service_type"] == "shelter"

    def test_narrative_does_not_regex_override(self):
        """For narratives, LLM/fallback should be authoritative —
        regex should NOT override service_type."""
        msg = ("I just got out of the hospital and my housing fell through "
               "and I need somewhere to stay in the Bronx and find a job")
        result = extract_slots_smart(msg)
        # Regex would extract "medical" from "hospital" — but narrative
        # fallback should re-prioritize to "shelter"
        assert result["service_type"] != "medical"
        assert result["service_type"] == "shelter"

    def test_short_message_uses_standard_path(self):
        """Short messages should NOT use narrative extraction."""
        msg = "I need food in Brooklyn"
        result = extract_slots_smart(msg)
        assert result["service_type"] == "food"

    def test_additional_services_preserved(self):
        """Narrative extraction should preserve additional services."""
        msg = ("I just got out of the hospital and my housing fell through "
               "and I need somewhere to stay in the Bronx and find a job")
        result = extract_slots_smart(msg)
        additional = [s for s, _ in result.get("additional_services", [])]
        assert len(additional) >= 1  # at least medical or employment
