"""
Query Executor — runs parameterized template queries against the Streetlives DB.

Architecture: This is the ONLY module that talks to the database.
All queries come from query_templates.py — never from LLM output.

Usage:
    from app.rag.query_executor import execute_service_query

    results = execute_service_query(
        template_key="food",
        user_params={"city": "Brooklyn", "age": 25},
    )
    # results = {
    #     "services": [{"service_name": "...", "address": "...", ...}, ...],
    #     "result_count": 3,
    #     "template_used": "FoodQuery",
    #     "params_applied": {"taxonomy_name": "Food", "city": "Brooklyn", "age": 25},
    #     "relaxed": False,
    # }
"""

import os
import time
import logging
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from dotenv import load_dotenv

from app.rag.query_templates import (
    build_query,
    build_relaxed_query,
    format_service_card,
    deduplicate_results,
    TEMPLATES,
)

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

_engine = None


def _get_engine():
    """Lazy-initialize the SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it to your .env file.\n"
                "Format: postgresql://user:password@host:port/streetlives"
            )
        _engine = create_engine(
            DATABASE_URL,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,   # verify connections before use
            echo=False,
        )
    return _engine


def test_connection() -> bool:
    """Verify the database is reachable."""
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            return result.fetchone()[0] == 1
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False


# ---------------------------------------------------------------------------
# QUERY EXECUTION
# ---------------------------------------------------------------------------

def execute_service_query(
    template_key: str,
    user_params: dict,
    max_results: int = 10,
    allow_relaxed: bool = True,
) -> dict:
    """
    Execute a service query using a pre-defined template.

    Args:
        template_key:  Key from TEMPLATES (e.g. "food", "shelter", "clothing")
        user_params:   Slot values from the intake form, e.g.
                       {"city": "Brooklyn", "age": 17, "gender": "male"}
        max_results:   Maximum number of service cards to return.
        allow_relaxed: If True and the strict query returns 0 results,
                       automatically retry with relaxed filters.

    Returns:
        dict with keys:
            services       — list of formatted service card dicts
            result_count   — number of results
            template_used  — human-readable template name
            params_applied — the actual parameters bound to the query
            relaxed        — True if the relaxed fallback was used
            execution_ms   — query execution time in milliseconds
    """
    if template_key not in TEMPLATES:
        return {
            "services": [],
            "result_count": 0,
            "template_used": None,
            "params_applied": user_params,
            "relaxed": False,
            "execution_ms": 0,
            "error": f"Unknown template: {template_key}",
        }

    params = dict(user_params)
    params["max_results"] = max_results

    # --- Strict query ---
    sql, bound_params = build_query(template_key, params)

    start = time.monotonic()
    rows = _execute_sql(sql, bound_params)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    results = deduplicate_results(rows)
    cards = [format_service_card(r) for r in results]

    if cards or not allow_relaxed:
        return {
            "services": cards,
            "result_count": len(cards),
            "template_used": TEMPLATES[template_key]["name"],
            "params_applied": bound_params,
            "relaxed": False,
            "execution_ms": elapsed_ms,
        }

    # --- Relaxed fallback ---
    logger.info(
        f"Strict query for '{template_key}' returned 0 results. "
        f"Retrying with relaxed filters."
    )

    sql_relaxed, relaxed_params = build_relaxed_query(template_key, params)

    start = time.monotonic()
    rows_relaxed = _execute_sql(sql_relaxed, relaxed_params)
    elapsed_ms += int((time.monotonic() - start) * 1000)

    results_relaxed = deduplicate_results(rows_relaxed)
    cards_relaxed = [format_service_card(r) for r in results_relaxed]

    return {
        "services": cards_relaxed,
        "result_count": len(cards_relaxed),
        "template_used": TEMPLATES[template_key]["name"],
        "params_applied": relaxed_params,
        "relaxed": True,
        "execution_ms": elapsed_ms,
    }


def _execute_sql(sql: str, params: dict) -> list[dict]:
    """
    Execute a parameterized SQL query and return rows as dicts.

    All SQL passed here MUST come from query_templates.py.
    This function never constructs SQL — it only executes it.
    """
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Query execution error: {e}")
        logger.debug(f"SQL: {sql}")
        logger.debug(f"Params: {params}")
        return []


# ---------------------------------------------------------------------------
# SLOT-TO-TEMPLATE MAPPING
# ---------------------------------------------------------------------------

# Maps the service_type values from slot_extractor.py to template keys.
# This bridges the gap between what the user says and what template to run.

SLOT_SERVICE_TO_TEMPLATE = {
    # Food
    "food":          "food",

    # Shelter & Housing
    "shelter":       "shelter",
    "housing":       "shelter",

    # Clothing
    "clothing":      "clothing",

    # Personal Care (showers, laundry, toiletries, haircuts)
    "personal_care": "personal_care",
    "shower":        "personal_care",

    # Health Care
    "medical":       "medical",
    "healthcare":    "medical",
    "health":        "medical",

    # Mental Health
    "mental_health": "mental_health",

    # Legal
    "legal":         "legal",

    # Employment
    "employment":    "employment",
    "job":           "employment",

    # Other Services
    "other":         "other",
    "benefits":      "other",
}


def resolve_template_key(service_type: str) -> Optional[str]:
    """
    Map a slot extractor service_type to a template key.

    Returns None if the service type is not recognized.
    """
    if not service_type:
        return None
    return SLOT_SERVICE_TO_TEMPLATE.get(service_type.lower())


# ---------------------------------------------------------------------------
# CITY / BOROUGH NORMALIZATION
# ---------------------------------------------------------------------------

# The DB uses city names (from physical_addresses.city), not borough names.
# But users often say "Queens" or "the Bronx". This mapping handles common
# NYC borough names and neighborhoods that map to DB city values.

NYC_LOCATION_ALIASES = {
    # Boroughs → city values used in the DB
    "manhattan":      "New York",
    "brooklyn":       "Brooklyn",
    "queens":         "Queens",
    "bronx":          "Bronx",
    "the bronx":      "Bronx",
    "staten island":  "Staten Island",

    # Common neighborhood → borough mappings
    "harlem":         "New York",
    "midtown":        "New York",
    "soho":           "New York",
    "east village":   "New York",
    "west village":   "New York",
    "chelsea":        "New York",
    "tribeca":        "New York",
    "lower east side":"New York",
    "upper west side":"New York",
    "upper east side":"New York",
    "washington heights": "New York",
    "inwood":         "New York",

    "williamsburg":   "Brooklyn",
    "bushwick":       "Brooklyn",
    "bed-stuy":       "Brooklyn",
    "bedford-stuyvesant": "Brooklyn",
    "east new york":  "Brooklyn",
    "crown heights":  "Brooklyn",
    "flatbush":       "Brooklyn",
    "brownsville":    "Brooklyn",
    "sunset park":    "Brooklyn",
    "bay ridge":      "Brooklyn",

    "astoria":        "Queens",
    "flushing":       "Queens",
    "jamaica":        "Queens",
    "long island city": "Queens",
    "jackson heights": "Queens",
    "far rockaway":   "Queens",

    "south bronx":    "Bronx",
    "mott haven":     "Bronx",
    "fordham":        "Bronx",
    "hunts point":    "Bronx",
    "morrisania":     "Bronx",
}

# Borough-level entries — these get the full neighborhood expansion.
# Neighborhood-level entries should try a direct match first.
_BOROUGH_KEYS = {
    "manhattan", "brooklyn", "queens", "bronx", "the bronx", "staten island",
}


def is_borough(raw_location: str) -> bool:
    """Check if a location string is a borough (vs a neighborhood)."""
    if not raw_location:
        return False
    return raw_location.lower().strip() in _BOROUGH_KEYS


def normalize_location(raw_location: str) -> str:
    """
    Normalize a user-provided location string to a DB-compatible city value.

    Falls back to the original string if no alias is found — the query
    will still work, it just might not match any rows.
    """
    if not raw_location:
        return raw_location
    return NYC_LOCATION_ALIASES.get(raw_location.lower().strip(), raw_location.strip())


# ---------------------------------------------------------------------------
# BOROUGH EXPANSION
# ---------------------------------------------------------------------------
# When a user says "Queens", the DB might store the location's city as
# "Jamaica", "Flushing", "Astoria", etc. This reverse map lets us search
# for ALL city values that belong to a borough.

def _build_borough_to_cities() -> dict:
    """Build a reverse map from borough DB city → all city values in that borough."""
    borough_cities = {}
    for alias, city in NYC_LOCATION_ALIASES.items():
        if city not in borough_cities:
            borough_cities[city] = {city}
        # The alias might be a neighborhood name that the DB uses as a city value
        alias_city = alias.title()
        borough_cities[city].add(alias_city)
    return {k: sorted(v) for k, v in borough_cities.items()}


BOROUGH_TO_CITIES = _build_borough_to_cities()


def get_borough_city_names(city: str) -> list[str]:
    """
    Given a normalized borough city value (e.g. "Queens"), return all
    city values that might appear in the DB for that borough.

    Returns a lowercased list for case-insensitive SQL matching.

    Example:
        get_borough_city_names("Queens")
        → ["astoria", "far rockaway", "flushing", "jackson heights",
           "jamaica", "long island city", "queens"]
    """
    cities = BOROUGH_TO_CITIES.get(city, [city])
    return [c.lower() for c in cities]
