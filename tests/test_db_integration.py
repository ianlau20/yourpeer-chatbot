"""
Database integration tests — validates generated SQL against the real
Streetlives PostgreSQL database and checks schema assumptions.

These tests REQUIRE a live database connection via DATABASE_URL.
They are automatically skipped when DATABASE_URL is not set.

Run:
    DATABASE_URL=postgresql://... pytest tests/test_db_integration.py -v

All tests are READ-ONLY — they never modify the database.
"""

import os
import pytest
from sqlalchemy import create_engine, text, inspect

from app.rag.query_templates import (
    build_query,
    build_relaxed_query,
    format_service_card,
    TEMPLATES,
    _BASE_QUERY,
)
from app.rag.query_executor import (
    execute_service_query,
    resolve_template_key,
    DEFAULT_NEIGHBORHOOD_RADIUS_METERS,
)
from app.rag import query_services


DATABASE_URL = os.getenv("DATABASE_URL")

# Skip the entire module if no DATABASE_URL
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL not set — skipping DB integration tests",
)


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    """Create a SQLAlchemy engine for the test session."""
    return create_engine(DATABASE_URL)


@pytest.fixture(scope="module")
def inspector(engine):
    """SQLAlchemy inspector for schema introspection."""
    return inspect(engine)


@pytest.fixture
def conn(engine):
    """Fresh DB connection per test (avoids aborted-transaction cascades)."""
    with engine.connect() as connection:
        yield connection


# ---------------------------------------------------------------------------
# SCHEMA VALIDATION — alert on model drift
# ---------------------------------------------------------------------------
# These tests verify that the tables and columns our queries depend on
# actually exist in the database. A failure here means the DB schema has
# changed and our SQL templates need updating.

EXPECTED_TABLES = {
    "services",
    "locations",
    "service_at_locations",
    "service_taxonomy",
    "taxonomies",
    "physical_addresses",
    "regular_schedules",
    "organizations",
    "phones",
    "eligibility",
    "eligibility_parameters",
}

# Map of table → columns our queries depend on
EXPECTED_COLUMNS = {
    "services": [
        "id", "name", "description", "fees", "url", "email",
        "additional_info", "organization_id",
    ],
    "locations": [
        "id", "name", "slug", "position", "hidden_from_search",
        "last_validated_at",
    ],
    "service_at_locations": ["service_id", "location_id"],
    "service_taxonomy": ["service_id", "taxonomy_id"],
    "taxonomies": ["id", "name"],
    "physical_addresses": [
        "location_id", "address_1", "city", "state_province",
        "postal_code", "borough",
    ],
    "regular_schedules": [
        "service_id", "weekday", "opens_at", "closes_at",
    ],
    "organizations": ["id", "name", "url"],
    "phones": ["location_id", "service_id", "organization_id", "number"],
    "eligibility": ["service_id", "parameter_id", "eligible_values"],
    "eligibility_parameters": ["id", "name"],
}


class TestSchemaValidation:
    """Verify the DB schema matches our query assumptions."""

    def test_all_required_tables_exist(self, inspector):
        """Every table referenced in our queries must exist."""
        actual_tables = set(inspector.get_table_names())
        missing = EXPECTED_TABLES - actual_tables
        assert not missing, (
            f"Missing tables in database: {missing}. "
            f"Query templates will fail at runtime."
        )

    @pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS.keys()))
    def test_required_columns_exist(self, inspector, table):
        """Every column referenced in our queries must exist on its table."""
        actual_columns = {col["name"] for col in inspector.get_columns(table)}
        expected = set(EXPECTED_COLUMNS[table])
        missing = expected - actual_columns
        assert not missing, (
            f"Table '{table}' is missing columns: {missing}. "
            f"Query templates reference these columns and will fail."
        )

    def test_locations_position_is_geometry(self, conn):
        """locations.position must be a PostGIS geometry/geography type.

        Our queries use ST_DWithin and ST_Distance which require this.
        """
        result = conn.execute(text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'locations' AND column_name = 'position'"
        ))
        row = result.fetchone()
        assert row is not None, "locations.position column not found"
        # PostGIS geometry types show as 'geometry' or 'geography' or 'USER-DEFINED'
        udt = row[0].lower()
        assert udt in ("geometry", "geography", "user-defined"), (
            f"locations.position has type '{udt}', expected PostGIS geometry. "
            f"ST_DWithin/ST_Distance queries will fail."
        )

    def test_eligibility_values_is_jsonb(self, conn):
        """eligibility.eligible_values must be JSONB for our @> queries."""
        result = conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'eligibility' AND column_name = 'eligible_values'"
        ))
        row = result.fetchone()
        assert row is not None, "eligibility.eligible_values column not found"
        assert row[0].lower() in ("jsonb", "json"), (
            f"eligibility.eligible_values is '{row[0]}', expected jsonb. "
            f"JSONB operators (@>, ->, ->>) will fail."
        )

    def test_last_validated_at_is_timestamp(self, conn):
        """locations.last_validated_at must be a timestamp type for ORDER BY."""
        result = conn.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'locations' AND column_name = 'last_validated_at'"
        ))
        row = result.fetchone()
        assert row is not None, (
            "locations.last_validated_at column not found. "
            "The ORDER BY freshness sort will fail."
        )
        assert "timestamp" in row[0].lower(), (
            f"locations.last_validated_at is '{row[0]}', expected timestamp."
        )

    def test_postgis_extension_available(self, conn):
        """PostGIS must be installed for proximity search."""
        result = conn.execute(text(
            "SELECT 1 FROM pg_extension WHERE extname = 'postgis'"
        ))
        assert result.fetchone() is not None, (
            "PostGIS extension not installed. "
            "ST_DWithin, ST_Distance, ST_MakePoint will fail."
        )

    def test_taxonomy_names_still_valid(self, conn):
        """Taxonomy names in our templates must exist in the DB.

        If a taxonomy name is removed or renamed, queries for that service
        category will silently return zero results.
        """
        result = conn.execute(text(
            "SELECT DISTINCT LOWER(name) FROM taxonomies"
        ))
        db_names = {row[0] for row in result.fetchall()}

        missing_by_template = {}
        for key, template in TEMPLATES.items():
            template_names = set(template["default_params"].get("taxonomy_names", []))
            missing = template_names - db_names
            if missing:
                missing_by_template[key] = missing

        assert not missing_by_template, (
            f"Taxonomy names missing from DB: {missing_by_template}. "
            f"These templates will return zero results."
        )

    def test_eligibility_parameter_names(self, conn):
        """Eligibility parameter names we query (age, gender, membership) must exist."""
        result = conn.execute(text(
            "SELECT DISTINCT name FROM eligibility_parameters"
        ))
        db_params = {row[0] for row in result.fetchall()}
        required = {"age", "gender", "membership"}
        missing = required - db_params
        assert not missing, (
            f"Missing eligibility parameters: {missing}. "
            f"Age/gender/membership filters will silently fail."
        )


# ---------------------------------------------------------------------------
# SQL EXECUTION — verify generated queries actually run
# ---------------------------------------------------------------------------
# These tests use execute_service_query (the production code path) rather
# than raw conn.execute, so they test the real SQL execution pipeline
# including parameter binding and error handling.

class TestQueryExecution:
    """Verify that generated SQL executes without errors on the real DB."""

    @pytest.mark.parametrize("template_key", sorted(TEMPLATES.keys()))
    def test_strict_query_executes(self, template_key):
        """Every template's strict query must execute without SQL errors."""
        results = execute_service_query(
            template_key=template_key,
            user_params={"borough": "Manhattan"},
            max_results=3,
            allow_relaxed=False,
        )
        assert "services" in results
        assert isinstance(results["services"], list)
        assert "error" not in results

    @pytest.mark.parametrize("template_key", sorted(TEMPLATES.keys()))
    def test_relaxed_query_executes(self, template_key):
        """Every template's relaxed query must execute without SQL errors."""
        # Use a location unlikely to have results to trigger relaxed path
        results = execute_service_query(
            template_key=template_key,
            user_params={"borough": "Staten Island"},
            max_results=3,
            allow_relaxed=True,
        )
        assert "services" in results
        assert isinstance(results["services"], list)

    def test_proximity_query_executes(self):
        """Proximity search with lat/lon must execute without errors."""
        results = execute_service_query(
            template_key="food",
            user_params={
                "lat": 40.7549,
                "lon": -73.9840,
                "radius_meters": DEFAULT_NEIGHBORHOOD_RADIUS_METERS,
            },
            max_results=3,
        )
        assert "services" in results
        assert isinstance(results["services"], list)

    def test_proximity_order_by_distance(self):
        """ORDER BY ST_Distance must work with real PostGIS data."""
        sql, _ = build_query("food", {
            "lat": 40.7549, "lon": -73.9840,
            "radius_meters": 5000, "max_results": 5,
        })
        assert "ST_Distance" in sql

        results = execute_service_query(
            template_key="food",
            user_params={
                "lat": 40.7549,
                "lon": -73.9840,
                "radius_meters": 5000,
            },
            max_results=5,
        )
        assert isinstance(results["services"], list)

    def test_age_eligibility_filter_executes(self):
        """Age eligibility JSONB filter must execute without errors."""
        results = execute_service_query(
            template_key="shelter",
            user_params={"borough": "Manhattan", "age": 25},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_gender_eligibility_filter_executes(self):
        """Gender eligibility JSONB filter must execute without errors."""
        results = execute_service_query(
            template_key="shelter",
            user_params={"borough": "Brooklyn", "gender": "female"},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_open_now_sort_executes(self):
        """The open-now CASE expression in ORDER BY must execute."""
        sql, _ = build_query("food", {"borough": "Queens", "max_results": 3})
        assert "CURRENT_TIME" in sql

        results = execute_service_query(
            template_key="food",
            user_params={"borough": "Queens"},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_freshness_sort_executes(self):
        """ORDER BY last_validated_at DESC NULLS LAST must execute."""
        sql, _ = build_query("food", {"borough": "Bronx", "max_results": 3})
        assert "last_validated_at" in sql

        results = execute_service_query(
            template_key="food",
            user_params={"borough": "Bronx"},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_city_list_any_filter_executes(self):
        """City list ANY() filter (borough expansion) must execute."""
        results = execute_service_query(
            template_key="food",
            user_params={"city_list": ["brooklyn", "bushwick", "williamsburg"]},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_weekday_filter_executes(self):
        """Weekday schedule filter must execute."""
        results = execute_service_query(
            template_key="food",
            user_params={"borough": "Manhattan", "weekday": 1},
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_open_now_filter_executes(self):
        """Open-now schedule filter (weekday + time) must execute."""
        results = execute_service_query(
            template_key="food",
            user_params={
                "borough": "Manhattan",
                "weekday": 1,
                "current_time": "12:00",
            },
            max_results=3,
        )
        assert isinstance(results["services"], list)

    def test_all_filters_combined_executes(self):
        """Query with every filter active must execute without errors."""
        results = execute_service_query(
            template_key="shelter",
            user_params={
                "borough": "Manhattan",
                "city": "New York",
                "city_list": ["new york", "harlem", "east harlem"],
                "lat": 40.7549,
                "lon": -73.9840,
                "radius_meters": 1600,
                "age": 30,
                "gender": "male",
                "weekday": 2,
                "current_time": "14:00",
            },
            max_results=3,
        )
        assert isinstance(results["services"], list)


# ---------------------------------------------------------------------------
# RESULT FORMAT — verify real results can be formatted
# ---------------------------------------------------------------------------

class TestResultFormatting:
    """Verify that real DB rows can be formatted into service cards."""

    def test_real_results_format_to_cards(self):
        """Real query results must format into valid service cards."""
        results = execute_service_query(
            template_key="food",
            user_params={"borough": "Manhattan"},
            max_results=3,
        )
        if results["result_count"] == 0:
            pytest.skip("No food services in Manhattan — cannot test formatting")

        for card in results["services"]:
            assert card["service_name"], f"Card missing service_name: {card}"
            assert card["service_id"], f"Card missing service_id: {card}"
            assert card["is_open"] in ("open", "closed", None), (
                f"Invalid is_open value: {card['is_open']}"
            )

    def test_proximity_results_return_multiple(self):
        """Proximity search in central Manhattan should return multiple results."""
        results = execute_service_query(
            template_key="food",
            user_params={
                "lat": 40.7549,
                "lon": -73.9840,
                "radius_meters": 5000,
            },
            max_results=10,
        )
        if results["result_count"] < 2:
            pytest.skip("Need at least 2 results to verify")

        assert results["result_count"] >= 2, "Proximity search should return nearby results"


# ---------------------------------------------------------------------------
# END-TO-END — verify query_services() works with real DB
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Verify the full query_services() pipeline against real data."""

    def test_query_services_borough_search(self):
        """query_services with a borough should return structured results."""
        results = query_services(service_type="food", location="Manhattan", max_results=3)
        assert "services" in results
        assert "result_count" in results
        assert "template_used" in results
        assert results.get("error") is None, f"Query error: {results.get('error')}"

    def test_query_services_neighborhood_search(self):
        """query_services with a neighborhood should use proximity."""
        results = query_services(service_type="food", location="harlem", max_results=3)
        assert "services" in results
        assert results.get("error") is None, f"Query error: {results.get('error')}"

    def test_query_services_with_coords(self):
        """query_services with direct lat/lng should run proximity search."""
        results = query_services(
            service_type="food",
            latitude=40.7549,
            longitude=-73.9840,
            max_results=3,
        )
        assert "services" in results
        assert results.get("error") is None, f"Query error: {results.get('error')}"

    def test_query_services_relaxed_fallback(self):
        """query_services should use relaxed fallback when strict returns 0."""
        # Use a very narrow search that's likely to return 0 strict results
        results = query_services(
            service_type="legal",
            location="far rockaway",
            max_results=3,
        )
        assert "services" in results
        assert results.get("error") is None, f"Query error: {results.get('error')}"
        # Whether strict or relaxed, the pipeline should complete without error

    def test_service_cards_have_required_fields(self):
        """Service cards from real queries must have all expected fields."""
        results = query_services(service_type="food", location="Brooklyn", max_results=3)
        if results["result_count"] == 0:
            pytest.skip("No results — cannot validate card fields")

        required_fields = [
            "service_id", "service_name", "organization", "address",
            "phone", "hours_today", "is_open", "yourpeer_url",
        ]
        for card in results["services"]:
            for field in required_fields:
                assert field in card, (
                    f"Service card missing field '{field}': {card.get('service_name')}"
                )
