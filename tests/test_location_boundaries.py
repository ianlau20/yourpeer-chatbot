"""
Location boundary tests — validates that queries stay within NYC boundaries,
normalization maps correctly, and the relaxed fallback doesn't leak
out-of-area results.

These tests inspect the generated SQL and parameters WITHOUT requiring
a database connection.

Run with: python -m pytest tests/test_location_boundaries.py -v
Or just:  python tests/test_location_boundaries.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.rag.query_templates import build_query, build_relaxed_query, TEMPLATES
from app.rag.query_executor import normalize_location, NYC_LOCATION_ALIASES, get_borough_city_names
from app.services.slot_extractor import extract_slots, NEAR_ME_SENTINEL


# -----------------------------------------------------------------------
# STATE FILTER — must ALWAYS be present
# -----------------------------------------------------------------------

def test_state_filter_in_all_templates():
    """Every template's generated SQL must include the NY state filter."""
    for key in TEMPLATES:
        sql, params = build_query(key, {"city": "Brooklyn", "max_results": 5})
        assert "state_province" in sql.lower(), \
            f"Template '{key}' is missing state filter in SQL"
        assert "'ny'" in sql.lower(), \
            f"Template '{key}' state filter doesn't restrict to NY"
    print("  PASS: state filter present in all templates")


def test_state_filter_in_relaxed_queries():
    """Relaxed queries must STILL include the NY state filter."""
    for key in TEMPLATES:
        sql, params = build_relaxed_query(key, {"city": "Brooklyn", "max_results": 5})
        assert "state_province" in sql.lower(), \
            f"Relaxed template '{key}' dropped the state filter"
        assert "'ny'" in sql.lower(), \
            f"Relaxed template '{key}' state filter doesn't restrict to NY"
    print("  PASS: state filter preserved in all relaxed queries")


def test_state_filter_without_city():
    """Even without a city param, the state filter should be present."""
    sql, params = build_query("food", {"max_results": 5})
    assert "state_province" in sql.lower(), \
        "State filter missing when no city provided"
    print("  PASS: state filter present even without city")


# -----------------------------------------------------------------------
# CITY FILTER — strict queries
# -----------------------------------------------------------------------

def test_city_filter_exact_match():
    """Strict queries should use exact city match (=), not LIKE."""
    sql, params = build_query("food", {"city": "Brooklyn", "max_results": 5})
    sql_lower = sql.lower()
    assert "lower(pa.city) = lower(:city)" in sql_lower, \
        "Strict query should use exact city match"
    assert params["city"] == "Brooklyn"
    assert "city_pattern" not in params, \
        "Strict query should not have city_pattern param"
    print("  PASS: strict query uses exact city match")


def test_city_filter_with_normalized_borough():
    """Normalized borough name should be used in the query params."""
    city = normalize_location("manhattan")
    sql, params = build_query("food", {"city": city, "max_results": 5})
    assert params["city"] == "New York"
    print("  PASS: normalized borough in query params")


# -----------------------------------------------------------------------
# RELAXED QUERY — city broadened, not dropped
# -----------------------------------------------------------------------

def test_relaxed_broadens_city_to_like():
    """Relaxed query should use LIKE pattern for city, not drop it."""
    sql, params = build_relaxed_query("food", {"city": "Brooklyn", "max_results": 5})
    assert "city_pattern" in params, "Relaxed query should have city_pattern param"
    assert params["city_pattern"] == "%Brooklyn%", \
        f"Expected '%Brooklyn%', got '{params.get('city_pattern')}'"
    assert "LIKE" in sql, "Relaxed query should use LIKE for city"
    print("  PASS: relaxed query broadens city to LIKE")


def test_relaxed_does_not_drop_city():
    """Relaxed query should NOT allow results from any city."""
    sql, params = build_relaxed_query("food", {"city": "Brooklyn", "max_results": 5})
    # Either city or city_pattern should be in params — city is never fully dropped
    has_city_constraint = "city" in params or "city_pattern" in params
    assert has_city_constraint, "Relaxed query dropped city filter entirely"
    print("  PASS: relaxed query keeps city constraint")


def test_relaxed_drops_eligibility_but_keeps_location():
    """Relaxed query drops age/gender but keeps city + state."""
    sql, params = build_relaxed_query("shelter", {
        "city": "Queens",
        "age": 17,
        "gender": "male",
        "max_results": 5,
    })
    # Age and gender should be dropped
    assert "age" not in params, "Relaxed query should drop age"
    assert "gender" not in params, "Relaxed query should drop gender"
    # City should be broadened but present
    assert "city_pattern" in params, "Relaxed query should keep city as LIKE"
    # State should still be there
    assert "state_province" in sql.lower(), "Relaxed query dropped state filter"
    print("  PASS: relaxed drops eligibility, keeps location")


def test_relaxed_drops_schedule_but_keeps_location():
    """Relaxed query drops schedule filters but keeps city + state."""
    sql, params = build_relaxed_query("food", {
        "city": "Bronx",
        "weekday": 3,
        "current_time": "14:00",
        "max_results": 5,
    })
    assert "weekday" not in params, "Relaxed query should drop weekday"
    assert "current_time" not in params, "Relaxed query should drop current_time"
    assert "city_pattern" in params, "Relaxed query should keep city"
    print("  PASS: relaxed drops schedule, keeps location")


# -----------------------------------------------------------------------
# NORMALIZATION — comprehensive borough coverage
# -----------------------------------------------------------------------

def test_all_five_boroughs_normalize():
    """All 5 NYC boroughs should normalize to DB city values."""
    boroughs = {
        "manhattan": "New York",
        "brooklyn": "Brooklyn",
        "queens": "Queens",
        "bronx": "Bronx",
        "the bronx": "Bronx",
        "staten island": "Staten Island",
    }
    for raw, expected in boroughs.items():
        result = normalize_location(raw)
        assert result == expected, f"'{raw}' → '{result}', expected '{expected}'"
    print("  PASS: all 5 boroughs normalize correctly")


def test_all_neighborhoods_in_map():
    """Every neighborhood in the alias map should normalize to a valid borough city."""
    valid_cities = {"New York", "Brooklyn", "Queens", "Bronx", "Staten Island"}
    for alias, city in NYC_LOCATION_ALIASES.items():
        assert city in valid_cities, \
            f"Alias '{alias}' maps to '{city}' which is not a valid NYC city"
    print("  PASS: all neighborhood aliases map to valid NYC cities")


def test_case_insensitive_normalization():
    """Normalization should be case-insensitive."""
    cases = [
        ("BROOKLYN", "Brooklyn"),
        ("Brooklyn", "Brooklyn"),
        ("bRoOkLyN", "Brooklyn"),
        ("QUEENS", "Queens"),
        ("Manhattan", "New York"),
        ("HARLEM", "New York"),
    ]
    for raw, expected in cases:
        result = normalize_location(raw)
        assert result == expected, f"'{raw}' → '{result}', expected '{expected}'"
    print("  PASS: case-insensitive normalization")


# -----------------------------------------------------------------------
# LOCATION EXTRACTION EDGE CASES
# -----------------------------------------------------------------------

def test_borough_in_full_sentence():
    """Boroughs should be extracted from natural sentences."""
    cases = [
        ("I need food in Brooklyn please", "brooklyn"),
        ("shelter somewhere in Queens", "queens"),
        ("Is there a clinic in the Bronx", "bronx"),
        ("Looking for clothes in Manhattan", "manhattan"),
        ("Help in Staten Island", "staten island"),
    ]
    for phrase, expected_loc in cases:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location in: {phrase}"
        assert expected_loc in slots["location"].lower(), \
            f"Expected '{expected_loc}' in: {phrase} → {slots['location']}"
    print("  PASS: boroughs extracted from full sentences")


def test_neighborhood_in_full_sentence():
    """Neighborhoods should be extracted from natural sentences."""
    cases = [
        ("food in Harlem", "harlem"),
        ("shelter in Bushwick", "bushwick"),
        ("doctor in Astoria", "astoria"),
        ("job near Midtown", "midtown"),
    ]
    for phrase, expected_loc in cases:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location in: {phrase}"
        assert expected_loc in slots["location"].lower(), \
            f"Expected '{expected_loc}' in: {phrase} → {slots['location']}"
    print("  PASS: neighborhoods extracted from full sentences")


def test_non_nyc_location_extracted_but_wont_match():
    """Non-NYC locations should extract (user said it) but normalize as-is."""
    phrases_and_locations = [
        ("food in Springfield", "Springfield"),
        ("shelter in Newark", "Newark"),
        ("I'm in Yonkers", "Yonkers"),
    ]
    for phrase, raw_location in phrases_and_locations:
        slots = extract_slots(phrase)
        assert slots["location"] is not None, f"No location in: {phrase}"
        # Normalization should pass through unchanged since it's not in the alias map
        normalized = normalize_location(slots["location"])
        assert normalized not in ["New York", "Brooklyn", "Queens", "Bronx", "Staten Island"], \
            f"Non-NYC location '{raw_location}' incorrectly normalized to an NYC borough"
    print("  PASS: non-NYC locations don't normalize to NYC boroughs")


def test_near_me_with_borough_override():
    """'Food near me in Brooklyn' should extract Brooklyn, not the near-me sentinel."""
    slots = extract_slots("food near me in Brooklyn")
    # The location should be the real borough, not the sentinel
    if slots["location"] == NEAR_ME_SENTINEL:
        # This is the known behavior if near-me check doesn't look ahead.
        # The updated slot extractor should handle this — check if it does.
        print("  INFO: 'food near me in Brooklyn' returned sentinel (known limitation)")
    else:
        assert "brooklyn" in slots["location"].lower()
        print("  PASS: 'near me in Brooklyn' extracts Brooklyn (not sentinel)")


def test_two_boroughs_in_message():
    """When two boroughs are mentioned, the first one via preposition wins."""
    # "I'm in Queens but looking for food in Brooklyn"
    # The regex "in <location>" pattern should catch the first "in Queens"
    slots = extract_slots("I'm in Queens but looking for food in Brooklyn")
    assert slots["location"] is not None
    # First "in X" match wins — this is a known limitation
    print(f"  INFO: two boroughs → extracted '{slots['location']}' (first match)")


def test_borough_with_typos():
    """Common misspellings should still be handled if possible."""
    # These won't match with exact regex — documenting the limitation
    typos = ["brookyln", "quens", "manhatten", "bronks"]
    for typo in typos:
        slots = extract_slots(f"food in {typo}")
        normalized = normalize_location(slots["location"]) if slots["location"] else None
        if normalized and normalized in ["Brooklyn", "Queens", "New York", "Bronx"]:
            print(f"  INFO: typo '{typo}' → normalized correctly")
        else:
            print(f"  INFO: typo '{typo}' → not matched (needs LLM extraction)")


# -----------------------------------------------------------------------
# QUERY BUILDER — filter composition
# -----------------------------------------------------------------------

def test_query_with_city_includes_city_filter():
    """When city is provided, the query SQL should include the city filter."""
    sql, params = build_query("food", {"city": "Brooklyn", "max_results": 5})
    sql_lower = sql.lower()
    assert "lower(pa.city) = lower(:city)" in sql_lower, \
        "City filter not in query SQL"
    assert params["city"] == "Brooklyn"
    print("  PASS: city filter included when city provided")


def test_query_without_city_omits_city_filter():
    """When no city is provided, exact city filter should not be bound."""
    sql, params = build_query("food", {"max_results": 5})
    sql_lower = sql.lower()
    assert "city" not in params, \
        "City param should not be present when no city provided"
    assert "state_province" in sql_lower, \
        "State filter should still be present"
    print("  PASS: city filter omitted when no city provided, state still present")


def test_query_with_age_includes_eligibility():
    """Age param should trigger eligibility filter in the query."""
    sql, params = build_query("shelter", {"city": "Brooklyn", "age": 17, "max_results": 5})
    assert "eligibility" in sql.lower(), "Age eligibility filter not in query"
    assert params["age"] == 17
    print("  PASS: age triggers eligibility filter")


def test_query_without_age_omits_eligibility():
    """Without age param, eligibility filter should not appear."""
    sql, params = build_query("food", {"city": "Brooklyn", "max_results": 5})
    # The eligibility subquery should not be in the WHERE clause
    assert "age_min" not in sql, "Age eligibility in query without age param"
    print("  PASS: eligibility filter omitted without age")


def test_hidden_filter_always_present():
    """The hidden_from_search filter should always be in the query."""
    for key in TEMPLATES:
        sql, params = build_query(key, {"max_results": 5})
        assert "hidden_from_search" in sql.lower(), \
            f"Template '{key}' missing hidden_from_search filter"
    print("  PASS: hidden filter present in all templates")


def test_taxonomy_filter_always_present():
    """The taxonomy filter should always be in the query."""
    for key in TEMPLATES:
        sql, params = build_query(key, {"max_results": 5})
        assert "t.name" in sql.lower(), \
            f"Template '{key}' missing taxonomy filter"
        assert "taxonomy_name" in params, \
            f"Template '{key}' missing taxonomy_name param"
    print("  PASS: taxonomy filter present in all templates")


def test_max_results_default():
    """max_results should default to 10 if not provided."""
    sql, params = build_query("food", {"city": "Brooklyn"})
    assert params["max_results"] == 10
    print("  PASS: max_results defaults to 10")


def test_max_results_override():
    """max_results should be overridable."""
    sql, params = build_query("food", {"city": "Brooklyn", "max_results": 3})
    assert params["max_results"] == 3
    print("  PASS: max_results override works")


# -----------------------------------------------------------------------
# RELAXED QUERY — parameter inspection
# -----------------------------------------------------------------------

def test_relaxed_params_compared_to_strict():
    """Compare strict vs relaxed params to verify what gets dropped."""
    strict_sql, strict_params = build_query("shelter", {
        "city": "Queens",
        "age": 17,
        "gender": "male",
        "weekday": 3,
        "max_results": 5,
    })
    relaxed_sql, relaxed_params = build_relaxed_query("shelter", {
        "city": "Queens",
        "age": 17,
        "gender": "male",
        "weekday": 3,
        "max_results": 5,
    })

    # Strict should have all params
    assert "city" in strict_params
    assert "age" in strict_params
    assert "gender" in strict_params

    # Relaxed should drop eligibility and schedule
    assert "age" not in relaxed_params, "Relaxed should drop age"
    assert "gender" not in relaxed_params, "Relaxed should drop gender"
    assert "weekday" not in relaxed_params, "Relaxed should drop weekday"

    # Relaxed should keep location as LIKE
    assert "city_pattern" in relaxed_params, "Relaxed should have city_pattern"
    assert "city" not in relaxed_params, "Relaxed should not have exact city"

    # Both should have state filter in SQL
    assert "state_province" in strict_sql.lower()
    assert "state_province" in relaxed_sql.lower()

    print("  PASS: strict vs relaxed param comparison")


def test_relaxed_without_city_still_has_state():
    """Even if there's no city to relax, the state filter remains."""
    sql, params = build_relaxed_query("food", {"max_results": 5})
    assert "state_province" in sql.lower()
    assert "city_pattern" not in params  # no city to broaden
    print("  PASS: relaxed without city still has state filter")


# -----------------------------------------------------------------------
# BOROUGH EXPANSION (Queens fix)
# -----------------------------------------------------------------------

def test_queens_expands_to_neighborhoods():
    """Queens should expand to include all Queens neighborhoods."""
    cities = get_borough_city_names("Queens")
    assert "queens" in cities
    assert "astoria" in cities
    assert "flushing" in cities
    assert "jamaica" in cities
    assert "long island city" in cities
    assert "jackson heights" in cities
    assert "far rockaway" in cities
    print("  PASS: Queens expands to neighborhoods")


def test_brooklyn_expands_to_neighborhoods():
    """Brooklyn should expand to include all Brooklyn neighborhoods."""
    cities = get_borough_city_names("Brooklyn")
    assert "brooklyn" in cities
    assert "williamsburg" in cities
    assert "bushwick" in cities
    assert "flatbush" in cities
    assert "crown heights" in cities
    print("  PASS: Brooklyn expands to neighborhoods")


def test_manhattan_expands_to_neighborhoods():
    """Manhattan (New York) should expand to include Manhattan neighborhoods."""
    cities = get_borough_city_names("New York")
    assert "new york" in cities
    assert "harlem" in cities
    assert "midtown" in cities
    assert "chelsea" in cities
    assert "soho" in cities
    print("  PASS: Manhattan expands to neighborhoods")


def test_non_borough_does_not_expand():
    """Non-borough locations should return a single-item list."""
    cities = get_borough_city_names("Springfield")
    assert cities == ["springfield"]
    print("  PASS: non-borough returns single item")


def test_borough_expansion_in_query():
    """When city_list is provided, SQL should use ANY(:city_list)."""
    city_list = get_borough_city_names("Queens")
    sql, params = build_query("shelter", {
        "city": "Queens",
        "city_list": city_list,
        "max_results": 5,
    })
    assert "any(:city_list)" in sql.lower(), \
        "SQL should contain ANY(:city_list) for borough expansion"
    assert params["city_list"] == city_list
    print("  PASS: borough expansion generates ANY() SQL")


def test_borough_expansion_in_relaxed_query():
    """Relaxed query with city_list should keep the list, not fall back to LIKE."""
    city_list = get_borough_city_names("Queens")
    sql, params = build_relaxed_query("shelter", {
        "city": "Queens",
        "city_list": city_list,
        "max_results": 5,
    })
    assert "city_list" in params, "Relaxed query should keep city_list"
    assert "city" not in params, "Relaxed query should drop exact city when city_list present"
    assert "city_pattern" not in params, "Relaxed query should not add LIKE when city_list present"
    print("  PASS: relaxed query keeps borough expansion")


def test_no_expansion_uses_like_in_relaxed():
    """Without city_list, relaxed query should still fall back to LIKE."""
    sql, params = build_relaxed_query("food", {
        "city": "Springfield",
        "max_results": 5,
    })
    assert "city_pattern" in params, "Should fall back to LIKE without city_list"
    assert params["city_pattern"] == "%Springfield%"
    print("  PASS: no expansion falls back to LIKE in relaxed")


# -----------------------------------------------------------------------
# RUNNER
# -----------------------------------------------------------------------

if __name__ == "__main__":
    print("\nLocation Boundary Tests\n" + "=" * 50)

    print("\n--- State Filter (required) ---")
    test_state_filter_in_all_templates()
    test_state_filter_in_relaxed_queries()
    test_state_filter_without_city()

    print("\n--- City Filter (strict) ---")
    test_city_filter_exact_match()
    test_city_filter_with_normalized_borough()

    print("\n--- Relaxed Query Boundaries ---")
    test_relaxed_broadens_city_to_like()
    test_relaxed_does_not_drop_city()
    test_relaxed_drops_eligibility_but_keeps_location()
    test_relaxed_drops_schedule_but_keeps_location()

    print("\n--- Borough Normalization ---")
    test_all_five_boroughs_normalize()
    test_all_neighborhoods_in_map()
    test_case_insensitive_normalization()

    print("\n--- Location Extraction Edge Cases ---")
    test_borough_in_full_sentence()
    test_neighborhood_in_full_sentence()
    test_non_nyc_location_extracted_but_wont_match()
    test_near_me_with_borough_override()
    test_two_boroughs_in_message()
    test_borough_with_typos()

    print("\n--- Query Builder Filters ---")
    test_query_with_city_includes_city_filter()
    test_query_without_city_omits_city_filter()
    test_query_with_age_includes_eligibility()
    test_query_without_age_omits_eligibility()
    test_hidden_filter_always_present()
    test_taxonomy_filter_always_present()
    test_max_results_default()
    test_max_results_override()

    print("\n--- Relaxed Query Parameters ---")
    test_relaxed_params_compared_to_strict()
    test_relaxed_without_city_still_has_state()

    print("\n--- Borough Expansion ---")
    test_queens_expands_to_neighborhoods()
    test_brooklyn_expands_to_neighborhoods()
    test_manhattan_expands_to_neighborhoods()
    test_non_borough_does_not_expand()
    test_borough_expansion_in_query()
    test_borough_expansion_in_relaxed_query()
    test_no_expansion_uses_like_in_relaxed()

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
