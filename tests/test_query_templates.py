"""
Tests for query_templates.py — validates SQL generation, taxonomy name
correctness, service card formatting, schedule status computation,
time formatting, and result deduplication.

All tests run without a database connection by inspecting generated SQL
strings, parameters, and calling pure functions with mock data.

Run with: python -m pytest tests/test_query_templates.py -v
Or just:  python tests/test_query_templates.py
"""

import sys
import os
from datetime import time, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.rag.query_templates import (
    build_query,
    build_relaxed_query,
    format_service_card,
    deduplicate_results,
    _compute_schedule_status,
    _format_time,
    TEMPLATES,
    _BASE_QUERY,
)


# -----------------------------------------------------------------------
# TAXONOMY NAME CORRECTNESS
# -----------------------------------------------------------------------
# These are the actual taxonomy names in the Streetlives DB, confirmed
# from the yourpeer.nyc source code TAXONOMY_CATEGORIES constant.

VALID_DB_TAXONOMY_NAMES = {
    "Health", "Other service", "Shelter", "Food", "Clothing",
    "Personal Care", "Legal Services", "Mental Health", "Employment",
    "Advocates / Legal Aid", "Shower", "Toiletries", "Laundry",
}


def test_all_template_taxonomy_names_match_db():
    """Every template's default taxonomy_name must exist in the actual DB."""
    for key, template in TEMPLATES.items():
        name = template["default_params"]["taxonomy_name"]
        assert name in VALID_DB_TAXONOMY_NAMES, \
            f"Template '{key}' has taxonomy_name='{name}' which doesn't match any DB taxonomy. " \
            f"Valid names: {VALID_DB_TAXONOMY_NAMES}"
    print("  PASS: all template taxonomy names match DB")


def test_medical_taxonomy_is_health():
    """Medical template must use 'Health', not 'Healthcare'."""
    assert TEMPLATES["medical"]["default_params"]["taxonomy_name"] == "Health"
    print("  PASS: medical template uses 'Health'")


def test_legal_taxonomy_is_legal_services():
    """Legal template must use 'Legal Services', not 'Legal'."""
    assert TEMPLATES["legal"]["default_params"]["taxonomy_name"] == "Legal Services"
    print("  PASS: legal template uses 'Legal Services'")


def test_food_taxonomy():
    assert TEMPLATES["food"]["default_params"]["taxonomy_name"] == "Food"
    print("  PASS: food template taxonomy correct")


def test_shelter_taxonomy():
    assert TEMPLATES["shelter"]["default_params"]["taxonomy_name"] == "Shelter"
    print("  PASS: shelter template taxonomy correct")


def test_clothing_taxonomy():
    assert TEMPLATES["clothing"]["default_params"]["taxonomy_name"] == "Clothing"
    print("  PASS: clothing template taxonomy correct")


def test_employment_taxonomy():
    assert TEMPLATES["employment"]["default_params"]["taxonomy_name"] == "Employment"
    print("  PASS: employment template taxonomy correct")


def test_personal_care_taxonomy():
    assert TEMPLATES["personal_care"]["default_params"]["taxonomy_name"] == "Personal Care"
    print("  PASS: personal_care template taxonomy correct")


def test_mental_health_taxonomy():
    assert TEMPLATES["mental_health"]["default_params"]["taxonomy_name"] == "Mental Health"
    print("  PASS: mental_health template taxonomy correct")


def test_other_taxonomy():
    assert TEMPLATES["other"]["default_params"]["taxonomy_name"] == "Other service"
    print("  PASS: other template taxonomy correct")


# -----------------------------------------------------------------------
# BASE QUERY STRUCTURE
# -----------------------------------------------------------------------

def test_base_query_joins():
    """Base query must include all required table joins."""
    sql_lower = _BASE_QUERY.lower()
    assert "join service_taxonomy" in sql_lower
    assert "join taxonomies" in sql_lower
    assert "join service_at_locations" in sql_lower
    assert "join locations" in sql_lower
    assert "left join organizations" in sql_lower
    assert "left join physical_addresses" in sql_lower
    print("  PASS: base query has all required joins")


def test_base_query_phone_is_lateral():
    """Phone join should be LATERAL to prevent row multiplication."""
    sql_lower = _BASE_QUERY.lower()
    assert "lateral" in sql_lower, "Phone should use LATERAL join"
    assert "best_phone" in sql_lower, "Phone subquery should be aliased as best_phone"
    assert "limit 1" in sql_lower, "Phone subquery should LIMIT 1"
    print("  PASS: phone uses LATERAL join with LIMIT 1")


def test_base_query_phone_priority_order():
    """Phone LATERAL should prefer location > service > organization."""
    sql_lower = _BASE_QUERY.lower()
    # The CASE statement should order location first
    assert "when ph.location_id" in sql_lower
    assert "when ph.service_id" in sql_lower
    assert "when ph.organization_id" in sql_lower
    print("  PASS: phone priority order is location > service > org")


def test_base_query_schedule_lateral():
    """Schedule should use LATERAL join for today's hours."""
    sql_lower = _BASE_QUERY.lower()
    assert "today_sched" in sql_lower
    assert "regular_schedules" in sql_lower
    assert "isodow" in sql_lower
    print("  PASS: schedule uses LATERAL join for today")


def test_base_query_selects_slug():
    """Base query must select location slug for YourPeer URL."""
    sql_lower = _BASE_QUERY.lower()
    assert "l.slug" in sql_lower
    assert "location_slug" in sql_lower
    print("  PASS: base query selects location slug")


# -----------------------------------------------------------------------
# SERVICE CARD FORMATTING
# -----------------------------------------------------------------------

def _mock_row(**overrides):
    """Build a mock DB result row."""
    base = {
        "service_id": "test-uuid-123",
        "service_name": "Test Food Pantry",
        "service_description": "Free food distribution",
        "fees": "Free",
        "service_url": "https://example.com",
        "service_email": "info@example.com",
        "additional_info": "Bring ID",
        "organization_name": "Test Org",
        "organization_url": "https://testorg.com",
        "location_id": "loc-uuid-456",
        "location_name": "Main Office",
        "location_slug": "test-food-pantry-brooklyn",
        "address": "123 Main Street",
        "city": "Brooklyn",
        "state": "NY",
        "zip_code": "11201",
        "phone": "212-555-0001",
        "today_opens": None,
        "today_closes": None,
    }
    base.update(overrides)
    return base


def test_format_card_all_fields():
    """Service card should include all fields from a complete row."""
    card = format_service_card(_mock_row())
    assert card["service_name"] == "Test Food Pantry"
    assert card["organization"] == "Test Org"
    assert card["phone"] == "212-555-0001"
    assert "123 Main Street" in card["address"]
    assert "Brooklyn" in card["address"]
    assert "NY" in card["address"]
    assert card["fees"] == "Free"
    assert card["email"] == "info@example.com"
    print("  PASS: card formats all fields")


def test_format_card_yourpeer_url():
    """Card should build YourPeer URL from location slug."""
    card = format_service_card(_mock_row(location_slug="my-location"))
    assert card["yourpeer_url"] == "https://yourpeer.nyc/locations/my-location"
    print("  PASS: YourPeer URL from slug")


def test_format_card_no_slug():
    """Card should have None yourpeer_url if no slug."""
    card = format_service_card(_mock_row(location_slug=None))
    assert card["yourpeer_url"] is None
    print("  PASS: no slug → no YourPeer URL")


def test_format_card_missing_optional_fields():
    """Card should handle missing optional fields gracefully."""
    card = format_service_card(_mock_row(
        organization_name=None,
        phone=None,
        service_email=None,
        fees=None,
        service_description=None,
    ))
    assert card["service_name"] == "Test Food Pantry"
    assert card["organization"] is None
    assert card["phone"] is None
    assert card["email"] is None
    assert card["fees"] is None
    print("  PASS: missing optional fields handled")


def test_format_card_website_fallback():
    """Card should fall back to org URL if service URL is missing."""
    card = format_service_card(_mock_row(service_url=None, organization_url="https://org.com"))
    assert card["website"] == "https://org.com"
    print("  PASS: website falls back to org URL")


def test_format_card_website_prefers_service():
    """Card should prefer service URL over org URL."""
    card = format_service_card(_mock_row(
        service_url="https://service.com",
        organization_url="https://org.com",
    ))
    assert card["website"] == "https://service.com"
    print("  PASS: website prefers service URL")


def test_format_card_website_normalizes_missing_protocol():
    """URLs without a protocol should get https:// prepended."""
    # Bare domain
    card = format_service_card(_mock_row(service_url="www.example.com", organization_url=None))
    assert card["website"] == "https://www.example.com"

    # Domain with path
    card = format_service_card(_mock_row(service_url="example.org/services", organization_url=None))
    assert card["website"] == "https://example.org/services"

    # Org URL fallback also normalized
    card = format_service_card(_mock_row(service_url=None, organization_url="org.example.com"))
    assert card["website"] == "https://org.example.com"

    # Already has https — no change
    card = format_service_card(_mock_row(service_url="https://already-good.com"))
    assert card["website"] == "https://already-good.com"

    # Already has http — no change
    card = format_service_card(_mock_row(service_url="http://legacy.com"))
    assert card["website"] == "http://legacy.com"

    # Protocol-relative — no change
    card = format_service_card(_mock_row(service_url="//cdn.example.com"))
    assert card["website"] == "//cdn.example.com"

    # None/empty → None
    card = format_service_card(_mock_row(service_url=None, organization_url=None))
    assert card["website"] is None

    card = format_service_card(_mock_row(service_url="", organization_url=""))
    assert card["website"] is None

    # Whitespace-only → None
    card = format_service_card(_mock_row(service_url="  ", organization_url=None))
    assert card["website"] is None

    print("  PASS: website URLs normalized with protocol")


def test_format_card_no_address():
    """Card address should be None if all address parts are missing."""
    card = format_service_card(_mock_row(
        address=None, city=None, state=None, zip_code=None,
    ))
    assert card["address"] is None
    print("  PASS: no address parts → None")


def test_format_card_partial_address():
    """Card should build address from whatever parts are available."""
    card = format_service_card(_mock_row(address=None, state=None, zip_code=None))
    assert card["address"] == "Brooklyn"
    print("  PASS: partial address builds from available parts")


def test_format_card_default_service_name():
    """Card should show 'Unknown Service' if service_name is missing."""
    card = format_service_card(_mock_row(service_name=None))
    assert card["service_name"] == "Unknown Service"
    print("  PASS: missing service_name → 'Unknown Service'")


# -----------------------------------------------------------------------
# SCHEDULE STATUS
# -----------------------------------------------------------------------

def test_schedule_none_values():
    """None opens/closes should return no schedule data."""
    result = _compute_schedule_status(None, None)
    assert result["hours_today"] is None
    assert result["is_open"] is None
    print("  PASS: None schedule → no data")


def test_schedule_one_none():
    """One None value should return no schedule data."""
    assert _compute_schedule_status("09:00:00", None)["is_open"] is None
    assert _compute_schedule_status(None, "17:00:00")["is_open"] is None
    print("  PASS: partial None schedule → no data")


def test_schedule_string_times():
    """String time values (from DB) should parse correctly."""
    result = _compute_schedule_status("09:00:00", "17:00:00")
    assert result["hours_today"] == "9:00 AM – 5:00 PM"
    assert result["is_open"] in ("open", "closed")  # depends on current time
    print("  PASS: string times parse correctly")


def test_schedule_time_objects():
    """Python time objects should work."""
    result = _compute_schedule_status(time(9, 0), time(17, 0))
    assert result["hours_today"] == "9:00 AM – 5:00 PM"
    print("  PASS: time objects work")


def test_schedule_midnight_wrap():
    """Overnight schedules (e.g. 8PM-6AM) should format correctly."""
    result = _compute_schedule_status(time(20, 0), time(6, 0))
    assert result["hours_today"] == "8:00 PM – 6:00 AM"
    assert result["is_open"] in ("open", "closed")
    print("  PASS: midnight wrap formats correctly")


def test_schedule_invalid_string():
    """Invalid time strings should return no data, not crash."""
    result = _compute_schedule_status("not-a-time", "also-bad")
    assert result["hours_today"] is None
    assert result["is_open"] is None
    print("  PASS: invalid strings → graceful None")


def test_schedule_mixed_types():
    """Mixed string + time object should work."""
    result = _compute_schedule_status("09:00:00", time(17, 0))
    assert result["hours_today"] == "9:00 AM – 5:00 PM"
    print("  PASS: mixed types work")


def test_schedule_with_card():
    """Schedule data should flow through to the service card."""
    card = format_service_card(_mock_row(
        today_opens=time(9, 0),
        today_closes=time(17, 0),
    ))
    assert card["hours_today"] == "9:00 AM – 5:00 PM"
    assert card["is_open"] in ("open", "closed")
    print("  PASS: schedule flows through to card")


def test_schedule_no_data_in_card():
    """Card with no schedule data should show None."""
    card = format_service_card(_mock_row())
    assert card["hours_today"] is None
    assert card["is_open"] is None
    print("  PASS: no schedule → None in card")


# -----------------------------------------------------------------------
# TIME FORMATTING
# -----------------------------------------------------------------------

def test_format_time_morning():
    assert _format_time(time(9, 0)) == "9:00 AM"
    assert _format_time(time(9, 30)) == "9:30 AM"
    print("  PASS: morning times")


def test_format_time_afternoon():
    assert _format_time(time(14, 0)) == "2:00 PM"
    assert _format_time(time(17, 45)) == "5:45 PM"
    print("  PASS: afternoon times")


def test_format_time_noon():
    assert _format_time(time(12, 0)) == "12:00 PM"
    print("  PASS: noon")


def test_format_time_midnight():
    assert _format_time(time(0, 0)) == "12:00 AM"
    print("  PASS: midnight")


def test_format_time_just_after_midnight():
    assert _format_time(time(0, 30)) == "12:30 AM"
    print("  PASS: 12:30 AM")


def test_format_time_no_leading_zero():
    """Single-digit hours should NOT have a leading zero."""
    result = _format_time(time(9, 0))
    assert not result.startswith("0"), f"Leading zero in: {result}"
    result2 = _format_time(time(1, 0))
    assert not result2.startswith("0"), f"Leading zero in: {result2}"
    print("  PASS: no leading zeros")


# -----------------------------------------------------------------------
# DEDUPLICATION
# -----------------------------------------------------------------------

def test_deduplicate_removes_dupes():
    """Rows with the same service_id should be collapsed to one."""
    rows = [
        {"service_id": "aaa", "phone": "111"},
        {"service_id": "aaa", "phone": "222"},
        {"service_id": "bbb", "phone": "333"},
    ]
    result = deduplicate_results(rows)
    assert len(result) == 2
    assert result[0]["service_id"] == "aaa"
    assert result[1]["service_id"] == "bbb"
    print("  PASS: duplicates removed")


def test_deduplicate_keeps_first():
    """Should keep the first occurrence of each service_id."""
    rows = [
        {"service_id": "aaa", "phone": "first"},
        {"service_id": "aaa", "phone": "second"},
    ]
    result = deduplicate_results(rows)
    assert len(result) == 1
    assert result[0]["phone"] == "first"
    print("  PASS: keeps first occurrence")


def test_deduplicate_empty():
    """Empty list should return empty list."""
    assert deduplicate_results([]) == []
    print("  PASS: empty list")


def test_deduplicate_no_service_id():
    """Rows without service_id should be skipped."""
    rows = [
        {"service_id": None, "phone": "111"},
        {"service_id": "aaa", "phone": "222"},
    ]
    result = deduplicate_results(rows)
    assert len(result) == 1
    assert result[0]["service_id"] == "aaa"
    print("  PASS: rows without service_id skipped")


def test_deduplicate_all_unique():
    """All-unique rows should pass through unchanged."""
    rows = [
        {"service_id": "aaa", "phone": "111"},
        {"service_id": "bbb", "phone": "222"},
        {"service_id": "ccc", "phone": "333"},
    ]
    result = deduplicate_results(rows)
    assert len(result) == 3
    print("  PASS: all unique rows kept")


# -----------------------------------------------------------------------
# GENERATED SQL VALIDATION
# -----------------------------------------------------------------------

def test_generated_sql_is_parameterized():
    """Generated SQL should use :param placeholders, never string interpolation."""
    for key in TEMPLATES:
        sql, params = build_query(key, {"city": "Brooklyn", "age": 17, "max_results": 5})
        # Should have :param style placeholders
        assert ":taxonomy_name" in sql
        assert ":max_results" in sql
        # Should NOT have raw values injected
        assert "'Brooklyn'" not in sql, f"Template '{key}' has raw value in SQL"
        assert "17" not in sql.split("ISODOW")[0], \
            f"Template '{key}' may have raw age in SQL (check carefully)"
    print("  PASS: all SQL is parameterized")


def test_both_city_and_city_like_dont_conflict():
    """When strict query has exact city, LIKE pattern should NOT also be present."""
    sql, params = build_query("food", {"city": "Brooklyn", "max_results": 5})
    # Should have exact city but NOT city_pattern (that's for relaxed only)
    assert "city" in params
    assert "city_pattern" not in params
    print("  PASS: strict query has city but not city_pattern")


def test_relaxed_has_city_pattern_not_city():
    """Relaxed query should swap city for city_pattern."""
    sql, params = build_relaxed_query("food", {"city": "Brooklyn", "max_results": 5})
    assert "city_pattern" in params
    assert "city" not in params
    assert params["city_pattern"] == "%Brooklyn%"
    print("  PASS: relaxed query has city_pattern, not city")


def test_unknown_template_raises():
    """build_query with unknown template key should raise ValueError."""
    try:
        build_query("nonexistent", {"max_results": 5})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)
    print("  PASS: unknown template raises ValueError")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nQuery Templates Tests\n" + "=" * 50)

    print("\n--- Taxonomy Names ---")
    test_all_template_taxonomy_names_match_db()
    test_medical_taxonomy_is_health()
    test_legal_taxonomy_is_legal_services()
    test_food_taxonomy()
    test_shelter_taxonomy()
    test_clothing_taxonomy()
    test_employment_taxonomy()
    test_personal_care_taxonomy()
    test_mental_health_taxonomy()
    test_other_taxonomy()

    print("\n--- Base Query Structure ---")
    test_base_query_joins()
    test_base_query_phone_is_lateral()
    test_base_query_phone_priority_order()
    test_base_query_schedule_lateral()
    test_base_query_selects_slug()

    print("\n--- Service Card Formatting ---")
    test_format_card_all_fields()
    test_format_card_yourpeer_url()
    test_format_card_no_slug()
    test_format_card_missing_optional_fields()
    test_format_card_website_fallback()
    test_format_card_website_prefers_service()
    test_format_card_website_normalizes_missing_protocol()
    test_format_card_no_address()
    test_format_card_partial_address()
    test_format_card_default_service_name()

    print("\n--- Schedule Status ---")
    test_schedule_none_values()
    test_schedule_one_none()
    test_schedule_string_times()
    test_schedule_time_objects()
    test_schedule_midnight_wrap()
    test_schedule_invalid_string()
    test_schedule_mixed_types()
    test_schedule_with_card()
    test_schedule_no_data_in_card()

    print("\n--- Time Formatting ---")
    test_format_time_morning()
    test_format_time_afternoon()
    test_format_time_noon()
    test_format_time_midnight()
    test_format_time_just_after_midnight()
    test_format_time_no_leading_zero()

    print("\n--- Deduplication ---")
    test_deduplicate_removes_dupes()
    test_deduplicate_keeps_first()
    test_deduplicate_empty()
    test_deduplicate_no_service_id()
    test_deduplicate_all_unique()

    print("\n--- Generated SQL ---")
    test_generated_sql_is_parameterized()
    test_both_city_and_city_like_dont_conflict()
    test_relaxed_has_city_pattern_not_city()
    test_unknown_template_raises()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
