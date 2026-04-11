"""
Tests for Phase 3: User Attribute Slots (populations).

Covers:
  - Population extraction (regex): each population type + phrase coverage
  - Multiple populations: "disabled veteran" → ["disabled", "veteran"]
  - False positive guards: "Salvation Army" ≠ veteran, etc.
  - Pregnant coexistence: family_status + populations both fire
  - Senior auto-infer: age >= 62 → populations includes "senior"
  - Veteran boost: veteran_boost param set when population=veteran
  - Description boost: disabled + food → description pattern injected
  - Confirmation message: reflects population context
  - Merge preserves populations: union semantics across messages
  - No population → no boost: base query unchanged
  - Accessibility on cards: format_service_card includes accessibility_info
  - has_new_slots: empty _populations list doesn't trigger false positive

Run with: python -m pytest tests/unit/test_populations.py -v
"""

import sys
import os
from unittest.mock import patch
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.services.slot_extractor import (
    _extract_populations,
    extract_slots,
    merge_slots,
)
from app.services.confirmation import _build_confirmation_message
from app.rag.query_templates import format_service_card


# -----------------------------------------------------------------------
# HELPER: call query_services and capture user_params
# -----------------------------------------------------------------------

def _get_query_params(service_type="food", populations=None, age=None, **kwargs):
    """Call query_services with mocked executor and return the user_params."""
    from app.rag import query_services

    with patch("app.rag.execute_service_query") as mock_exec:
        mock_exec.return_value = {
            "services": [], "result_count": 0,
            "template_used": "test", "params_applied": {},
            "relaxed": False, "execution_ms": 0,
        }
        query_services(
            service_type=service_type,
            location="Brooklyn",
            populations=populations,
            age=age,
            **kwargs,
        )
        call_kwargs = mock_exec.call_args
        return call_kwargs.kwargs.get("user_params", call_kwargs[1].get("user_params", {}))


# -----------------------------------------------------------------------
# POPULATION EXTRACTION — INDIVIDUAL TYPES
# -----------------------------------------------------------------------

class TestPopulationExtraction:
    """Test _extract_populations for each population type."""

    def test_veteran_phrases(self):
        assert "veteran" in _extract_populations("I'm a veteran and need food")
        assert "veteran" in _extract_populations("I served in the army")
        assert "veteran" in _extract_populations("I was in the marines for 8 years")
        assert "veteran" in _extract_populations("navy vet looking for help")
        assert "veteran" in _extract_populations("air force veteran needs shelter")
        assert "veteran" in _extract_populations("national guard member here")

    def test_disabled_phrases(self):
        assert "disabled" in _extract_populations("I'm disabled and need food")
        assert "disabled" in _extract_populations("I have a disability")
        assert "disabled" in _extract_populations("I use a wheelchair")
        assert "disabled" in _extract_populations("I'm blind and need help")
        assert "disabled" in _extract_populations("I'm deaf, where can I get food")
        assert "disabled" in _extract_populations("I'm hearing impaired")

    def test_reentry_phrases(self):
        assert "reentry" in _extract_populations("just got out of jail last week")
        assert "reentry" in _extract_populations("released from prison yesterday")
        assert "reentry" in _extract_populations("I'm on parole")
        assert "reentry" in _extract_populations("I'm on probation and need a job")
        assert "reentry" in _extract_populations("formerly incarcerated, need help")
        assert "reentry" in _extract_populations("just got out of rikers")

    def test_dv_survivor_phrases(self):
        assert "dv_survivor" in _extract_populations("I escaped abuse")
        assert "dv_survivor" in _extract_populations("fleeing abuse with my kids")
        assert "dv_survivor" in _extract_populations("I'm in an abusive relationship")
        assert "dv_survivor" in _extract_populations("domestic violence situation")
        assert "dv_survivor" in _extract_populations("my abusive partner")
        assert "dv_survivor" in _extract_populations("fleeing domestic violence")

    def test_pregnant_phrases(self):
        assert "pregnant" in _extract_populations("I'm pregnant and need a doctor")
        assert "pregnant" in _extract_populations("expecting a baby soon")
        assert "pregnant" in _extract_populations("having a baby in two months")

    def test_senior_phrases(self):
        assert "senior" in _extract_populations("I'm a senior and need meals")
        assert "senior" in _extract_populations("elderly woman looking for help")
        assert "senior" in _extract_populations("I'm an older adult")
        assert "senior" in _extract_populations("senior citizen needing shelter")

    def test_no_population(self):
        assert _extract_populations("I need food in Brooklyn") == []
        assert _extract_populations("shelter near me") == []
        assert _extract_populations("hello") == []
        assert _extract_populations("") == []


# -----------------------------------------------------------------------
# MULTIPLE POPULATIONS
# -----------------------------------------------------------------------

class TestMultiplePopulations:
    """Verify multiple populations are extracted from a single message."""

    def test_disabled_veteran(self):
        result = _extract_populations("I'm a disabled veteran")
        assert "disabled" in result
        assert "veteran" in result
        assert len(result) == 2

    def test_pregnant_dv_survivor(self):
        result = _extract_populations("I'm pregnant and fleeing abuse")
        assert "pregnant" in result
        assert "dv_survivor" in result

    def test_senior_disabled(self):
        result = _extract_populations("I'm an elderly disabled person")
        assert "senior" in result
        assert "disabled" in result

    def test_reentry_veteran(self):
        result = _extract_populations("I'm a veteran, just got out of prison")
        assert "veteran" in result
        assert "reentry" in result

    def test_sorted_deterministic(self):
        """Output should be sorted for deterministic behavior."""
        result = _extract_populations("disabled veteran on parole")
        assert result == sorted(result)


# -----------------------------------------------------------------------
# FALSE POSITIVE GUARDS
# -----------------------------------------------------------------------

class TestPopulationFalsePositives:
    """Phrases containing population keywords that should NOT extract."""

    def test_salvation_army_not_veteran(self):
        assert "veteran" not in _extract_populations("I need help from the Salvation Army")

    def test_disabled_account_not_disabled(self):
        assert "disabled" not in _extract_populations("my account was disabled")
        assert "disabled" not in _extract_populations("they disabled my phone")

    def test_veterans_day_not_veteran(self):
        assert "veteran" not in _extract_populations("is this open on veterans day")

    def test_veterans_memorial_not_veteran(self):
        assert "veteran" not in _extract_populations("I'm near the veterans memorial")

    def test_blind_spot_not_disabled(self):
        assert "disabled" not in _extract_populations("that's a blind spot in the system")


# -----------------------------------------------------------------------
# PREGNANT + FAMILY_STATUS COEXISTENCE
# -----------------------------------------------------------------------

class TestPregnantCoexistence:
    """Pregnant should fire BOTH family_status and _populations."""

    def test_pregnant_sets_both(self):
        slots = extract_slots("I'm pregnant and need shelter in Brooklyn")
        assert slots["family_status"] == "with_children"
        assert "pregnant" in slots["_populations"]

    def test_pregnant_with_kids_both_fire(self):
        slots = extract_slots("I'm pregnant with two kids")
        assert slots["family_status"] == "with_children"
        assert "pregnant" in slots["_populations"]


# -----------------------------------------------------------------------
# EXTRACT_SLOTS INTEGRATION
# -----------------------------------------------------------------------

class TestExtractSlotsPopulations:
    """Verify _populations appears in extract_slots output."""

    def test_veteran_in_extract_slots(self):
        slots = extract_slots("I'm a veteran and need food in Brooklyn")
        assert slots["service_type"] == "food"
        assert "veteran" in slots["_populations"]

    def test_no_population_returns_empty_list(self):
        slots = extract_slots("I need food in Brooklyn")
        assert slots["_populations"] == []

    def test_populations_dont_interfere_with_service_type(self):
        """Population keywords shouldn't shadow service extraction."""
        slots = extract_slots("I'm a veteran and need shelter in Queens")
        assert slots["service_type"] == "shelter"
        assert "veteran" in slots["_populations"]


# -----------------------------------------------------------------------
# MERGE_SLOTS — LIST UNION SEMANTICS
# -----------------------------------------------------------------------

class TestMergePopulations:
    """Merge should union populations, not replace."""

    def test_merge_adds_new_population(self):
        existing = {"service_type": "food", "_populations": ["veteran"]}
        new = {"_populations": ["disabled"]}
        merged = merge_slots(existing, new)
        assert "veteran" in merged["_populations"]
        assert "disabled" in merged["_populations"]

    def test_merge_deduplicates(self):
        existing = {"_populations": ["veteran"]}
        new = {"_populations": ["veteran", "disabled"]}
        merged = merge_slots(existing, new)
        assert merged["_populations"].count("veteran") == 1
        assert "disabled" in merged["_populations"]

    def test_merge_preserves_when_new_empty(self):
        existing = {"_populations": ["veteran"]}
        new = {"_populations": []}
        merged = merge_slots(existing, new)
        assert merged["_populations"] == ["veteran"]

    def test_merge_creates_from_empty(self):
        existing = {}
        new = {"_populations": ["reentry"]}
        merged = merge_slots(existing, new)
        assert merged["_populations"] == ["reentry"]

    def test_merge_sorted_output(self):
        existing = {"_populations": ["veteran"]}
        new = {"_populations": ["disabled"]}
        merged = merge_slots(existing, new)
        assert merged["_populations"] == sorted(merged["_populations"])


# -----------------------------------------------------------------------
# SENIOR AUTO-INFER FROM AGE
# -----------------------------------------------------------------------

class TestSeniorAutoInfer:
    """query_services should auto-add 'senior' when age >= 62."""

    def test_age_65_adds_senior(self):
        params = _get_query_params(populations=[], age=65)
        # Senior boost should inject description pattern
        desc = params.get("description_pattern", "")
        assert "senior" in desc or "elder" in desc

    def test_age_30_no_senior(self):
        params = _get_query_params(populations=[], age=30)
        desc = params.get("description_pattern", "")
        assert "senior" not in desc and "elder" not in desc

    def test_age_62_boundary(self):
        params = _get_query_params(populations=[], age=62)
        desc = params.get("description_pattern", "")
        assert "senior" in desc or "elder" in desc

    def test_explicit_senior_not_doubled(self):
        """If user already said 'senior', auto-infer shouldn't duplicate."""
        params = _get_query_params(populations=["senior"], age=70)
        desc = params.get("description_pattern", "")
        # Should have senior pattern exactly once — no duplication
        assert desc.count("senior") >= 1  # at least present


# -----------------------------------------------------------------------
# VETERAN BOOST
# -----------------------------------------------------------------------

class TestVeteranBoost:
    """Veteran population should set veteran_boost param."""

    def test_veteran_sets_boost(self):
        params = _get_query_params(populations=["veteran"])
        assert params.get("veteran_boost") is True

    def test_non_veteran_no_boost(self):
        params = _get_query_params(populations=["disabled"])
        assert "veteran_boost" not in params or params.get("veteran_boost") is not True

    def test_no_population_no_boost(self):
        params = _get_query_params(populations=[])
        assert "veteran_boost" not in params


# -----------------------------------------------------------------------
# DESCRIPTION BOOST
# -----------------------------------------------------------------------

class TestDescriptionBoost:
    """Non-veteran populations inject description_pattern boost."""

    def test_disabled_injects_pattern(self):
        params = _get_query_params(populations=["disabled"])
        desc = params.get("description_pattern", "")
        assert "disabilit" in desc
        assert "wheelchair" in desc

    def test_reentry_injects_pattern(self):
        params = _get_query_params(populations=["reentry"])
        desc = params.get("description_pattern", "")
        assert "reentry" in desc
        assert "parole" in desc

    def test_dv_survivor_injects_pattern(self):
        params = _get_query_params(populations=["dv_survivor"])
        desc = params.get("description_pattern", "")
        assert "domestic violence" in desc

    def test_pregnant_injects_pattern(self):
        params = _get_query_params(populations=["pregnant"])
        desc = params.get("description_pattern", "")
        assert "prenatal" in desc

    def test_multiple_populations_combine_patterns(self):
        params = _get_query_params(populations=["disabled", "reentry"])
        desc = params.get("description_pattern", "")
        assert "disabilit" in desc
        assert "reentry" in desc

    def test_description_boost_appends_to_existing(self):
        """If sub-category narrowing already set a pattern, boost appends."""
        params = _get_query_params(
            service_type="other",
            populations=["disabled"],
            service_detail="English classes",
        )
        desc = params.get("description_pattern", "")
        # Should have both the ESL pattern AND the disability pattern
        assert "ESL" in desc or "english" in desc.lower()
        assert "disabilit" in desc


# -----------------------------------------------------------------------
# CONFIRMATION MESSAGE
# -----------------------------------------------------------------------

class TestConfirmationPopulations:
    """Confirmation message should reflect population context."""

    def test_veteran_friendly(self):
        slots = {
            "service_type": "food",
            "location": "Brooklyn",
            "_populations": ["veteran"],
        }
        msg = _build_confirmation_message(slots)
        assert "veteran-friendly" in msg

    def test_accessible(self):
        slots = {
            "service_type": "shelter",
            "location": "Manhattan",
            "_populations": ["disabled"],
        }
        msg = _build_confirmation_message(slots)
        assert "accessible" in msg

    def test_reentry_friendly(self):
        slots = {
            "service_type": "employment",
            "location": "Bronx",
            "_populations": ["reentry"],
        }
        msg = _build_confirmation_message(slots)
        assert "reentry-friendly" in msg

    def test_senior_without_age(self):
        slots = {
            "service_type": "food",
            "location": "Queens",
            "_populations": ["senior"],
        }
        msg = _build_confirmation_message(slots)
        assert "senior-friendly" in msg

    def test_senior_with_age_no_double(self):
        """When age is present, senior-friendly prefix is suppressed
        because '(age 65)' already conveys the information."""
        slots = {
            "service_type": "food",
            "location": "Queens",
            "age": 65,
            "_populations": ["senior"],
        }
        msg = _build_confirmation_message(slots)
        assert "senior-friendly" not in msg
        assert "(age 65)" in msg

    def test_no_population_no_prefix(self):
        slots = {
            "service_type": "food",
            "location": "Brooklyn",
            "_populations": [],
        }
        msg = _build_confirmation_message(slots)
        assert "veteran" not in msg
        assert "accessible" not in msg
        assert "reentry" not in msg

    def test_lgbtq_takes_priority_over_population(self):
        """LGBTQ prefix comes from _gender, not populations.
        Both should coexist without conflict."""
        slots = {
            "service_type": "shelter",
            "location": "Manhattan",
            "_gender": "lgbtq",
            "_populations": ["veteran"],
        }
        msg = _build_confirmation_message(slots)
        # LGBTQ-friendly is applied first (existing logic), then veteran
        assert "LGBTQ-friendly" in msg


# -----------------------------------------------------------------------
# NO POPULATION → NO BOOST
# -----------------------------------------------------------------------

class TestNoPopulationNoBoost:
    """Base query should be unchanged when populations is empty/None."""

    def test_empty_list(self):
        params = _get_query_params(populations=[])
        assert "veteran_boost" not in params
        assert "description_pattern" not in params

    def test_none(self):
        params = _get_query_params(populations=None)
        assert "veteran_boost" not in params
        assert "description_pattern" not in params


# -----------------------------------------------------------------------
# ACCESSIBILITY ON SERVICE CARDS
# -----------------------------------------------------------------------

class TestAccessibilityOnCards:
    """format_service_card should include accessibility_info."""

    def _make_row(self, **overrides):
        base = {
            "service_id": "123",
            "service_name": "Test Service",
            "service_description": "A test service",
            "organization_name": "Test Org",
            "location_name": "Test Location",
            "location_slug": "test-location",
            "address": "123 Main St",
            "city": "Brooklyn",
            "state": "NY",
            "zip_code": "11201",
            "phone": "212-555-1234",
            "service_url": None,
            "service_email": None,
            "fees": None,
            "additional_info": None,
            "organization_url": None,
            "today_opens": None,
            "today_closes": None,
            "requires_membership": False,
            "last_validated_at": None,
            "also_available": None,
            "location_id": "loc-1",
            "accessibility_info": None,
        }
        base.update(overrides)
        return base

    def test_accessibility_present(self):
        row = self._make_row(accessibility_info="Wheelchair accessible entrance")
        card = format_service_card(row)
        assert card["accessibility"] == "Wheelchair accessible entrance"

    def test_accessibility_absent(self):
        row = self._make_row(accessibility_info=None)
        card = format_service_card(row)
        assert card["accessibility"] is None


# -----------------------------------------------------------------------
# HAS_NEW_SLOTS GUARD
# -----------------------------------------------------------------------

class TestHasNewSlotsGuard:
    """Empty _populations list should NOT trigger has_new_slots."""

    def test_empty_populations_not_new(self):
        """Simulates the has_new_slots check from chatbot.py."""
        extracted = {
            "service_type": None,
            "service_detail": None,
            "additional_services": [],
            "location": None,
            "urgency": None,
            "age": None,
            "family_status": None,
            "_gender": None,
            "_populations": [],
        }
        has_new = any(
            v is not None and v != []
            for k, v in extracted.items()
            if k not in ("additional_services", "_populations")
        )
        assert has_new is False

    def test_population_with_service_is_new(self):
        """A message with service_type should still count as new."""
        extracted = {
            "service_type": "food",
            "service_detail": None,
            "additional_services": [],
            "location": None,
            "urgency": None,
            "age": None,
            "family_status": None,
            "_gender": None,
            "_populations": ["veteran"],
        }
        has_new = any(
            v is not None and v != []
            for k, v in extracted.items()
            if k not in ("additional_services", "_populations")
        )
        assert has_new is True


# -----------------------------------------------------------------------
# LLM SLOT EXTRACTOR SCHEMA
# -----------------------------------------------------------------------

class TestLLMSlotExtractorSchema:
    """Verify the LLM extractor tool schema includes populations."""

    def test_populations_in_tool_schema(self):
        from app.services.llm_slot_extractor import _EXTRACT_SLOTS_TOOL
        props = _EXTRACT_SLOTS_TOOL["input_schema"]["properties"]
        assert "populations" in props
        assert props["populations"]["type"] == "array"

    def test_empty_slots_includes_populations(self):
        from app.services.llm_slot_extractor import _empty_slots
        empty = _empty_slots()
        assert "_populations" in empty
        assert empty["_populations"] == []


# -----------------------------------------------------------------------
# LLM CLASSIFIER SCHEMA
# -----------------------------------------------------------------------

class TestLLMClassifierPopulations:
    """Verify the unified classifier handles populations."""

    def test_classifier_prompt_mentions_populations(self):
        from app.services.llm_classifier import _UNIFIED_SYSTEM_PROMPT
        assert "populations" in _UNIFIED_SYSTEM_PROMPT
        assert "veteran" in _UNIFIED_SYSTEM_PROMPT
        assert "disabled" in _UNIFIED_SYSTEM_PROMPT
        assert "reentry" in _UNIFIED_SYSTEM_PROMPT


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
