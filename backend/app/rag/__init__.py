"""
RAG module — Template-based query system for the Streetlives database.

This is NOT traditional RAG (retrieval-augmented generation).
The LLM is never used to generate service data. Instead:

    1. Slot extractor fills intake fields from conversation
    2. Template selector picks the right parameterized query
    3. Query executor runs it against the Streetlives DB
    4. Results come back as structured service cards

Public API:
    query_services(service_type, location, **slots) → dict
"""

from app.rag.query_executor import (
    execute_service_query,
    resolve_template_key,
    normalize_location,
    get_borough_city_names,
    get_neighborhood_center,
    is_borough,
    test_connection,
    DEFAULT_NEIGHBORHOOD_RADIUS_METERS,
)
from app.rag.query_templates import TEMPLATES, build_query


def query_services(
    service_type: str,
    location: str = None,
    age: int = None,
    gender: str = None,
    weekday: int = None,
    current_time: str = None,
    max_results: int = 10,
) -> dict:
    """
    High-level entry point: go from intake slots to service results.

    Args:
        service_type: From slot extractor (e.g. "food", "shelter", "medical")
        location:     User's location (borough, neighborhood, or city)
        age:          User's age (for eligibility filtering)
        gender:       User's gender (for gendered services)
        weekday:      Day of week 0=Mon..6=Sun (for schedule filtering)
        current_time: HH:MM string (for "open now" filtering)
        max_results:  Max service cards to return

    Returns:
        dict with keys: services, result_count, template_used,
                        params_applied, relaxed, execution_ms
        On error: dict with error key and empty services list.
    """
    # Map slot value to template key
    template_key = resolve_template_key(service_type)
    if not template_key:
        return {
            "services": [],
            "result_count": 0,
            "template_used": None,
            "params_applied": {"service_type": service_type},
            "relaxed": False,
            "execution_ms": 0,
            "error": (
                f"I don't have a search template for '{service_type}' yet. "
                f"I can help with: {', '.join(sorted(TEMPLATES.keys()))}."
            ),
        }

    # Normalize location to DB-compatible value and build query params
    user_params = {}
    if location:
        normalized_city = normalize_location(location)
        user_location_is_borough = is_borough(location)

        if user_location_is_borough:
            # Borough-level search: pass the borough name directly to use the
            # clean pa.borough column (avoids city field casing chaos).
            # Also keep city_list as a fallback for records where borough is NULL.
            user_params["borough"] = normalized_city
            city_list = get_borough_city_names(normalized_city)
            if len(city_list) > 1:
                user_params["city_list"] = city_list
        else:
            # Neighborhood-level search: use PostGIS proximity if we have
            # center coords, plus city filters as a safety net.
            center = get_neighborhood_center(location)

            if center:
                lat, lon = center
                user_params["lat"] = lat
                user_params["lon"] = lon
                user_params["radius_meters"] = DEFAULT_NEIGHBORHOOD_RADIUS_METERS

            # City-level filters keep results within the correct borough
            # even if PostGIS data is missing on some locations.
            user_params["city"] = normalized_city
            city_list = get_borough_city_names(normalized_city)
            if len(city_list) > 1:
                user_params["city_list"] = city_list
                user_params["_borough_city_list"] = city_list

    if age is not None:
        user_params["age"] = age
    if gender:
        user_params["gender"] = gender
    if weekday is not None:
        user_params["weekday"] = weekday
    if current_time:
        user_params["current_time"] = current_time

    return execute_service_query(
        template_key=template_key,
        user_params=user_params,
        max_results=max_results,
    )
