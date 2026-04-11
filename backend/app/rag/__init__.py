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
    latitude: float = None,
    longitude: float = None,
    family_status: str = None,
    colocated_service_types: list = None,
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
        latitude:     User's latitude from browser geolocation
        longitude:    User's longitude from browser geolocation
        family_status: Family composition ('with_children', 'with_family', 'alone')
        colocated_service_types: Additional service types that should be
                      co-located at the same location (e.g. ["clothing"]).
                      If provided, results are restricted to locations that
                      also have these services. Falls back to unrestricted
                      query if co-located search returns 0 results.

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

    # Direct browser geolocation: use lat/lng for proximity search
    if latitude is not None and longitude is not None:
        user_params["lat"] = latitude
        user_params["lon"] = longitude
        user_params["radius_meters"] = DEFAULT_NEIGHBORHOOD_RADIUS_METERS
    elif location:
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
        # The DB only has "male" and "female" in eligibility.eligible_values
        # for the gender parameter. Values like "transgender", "nonbinary",
        # and "lgbtq" would fail the @> check and wrongly EXCLUDE services
        # that have gender rules (e.g., a trans man would be excluded from
        # clothing pantries that accept males).
        #
        # Mapping:
        #   "male" / "female" → pass directly (matches DB values)
        #   "transgender"     → skip filter (no direction specified)
        #   "nonbinary"       → skip filter (not in DB)
        #   "lgbtq"           → skip filter (handled via taxonomy boost)
        _DB_GENDER_VALUES = {"male", "female"}
        if gender in _DB_GENDER_VALUES:
            user_params["gender"] = gender
        # else: gender signal is preserved in slots for taxonomy enrichment
        # and confirmation display, but not passed to the eligibility filter
    if weekday is not None:
        user_params["weekday"] = weekday
    if current_time:
        user_params["current_time"] = current_time

    # Shelter taxonomy enrichment based on user profile.
    # The DB has shelter sub-categories as separate taxonomy names with
    # parent_name="Shelter": "Families", "Single Adult", "Youth", "Senior",
    # "LGBTQ Young Adult", "Veterans". Services tagged as e.g. "Families"
    # are NOT also tagged with the generic "Shelter" taxonomy, so they're
    # invisible to the base shelter query unless explicitly included.
    if template_key == "shelter":
        extra_taxonomies = []

        # Family composition
        if family_status in ("with_children", "with_family"):
            extra_taxonomies.append("families")
        elif family_status == "alone":
            extra_taxonomies.append("single adult")

        # Age-based sub-categories
        if age is not None and age < 18:
            extra_taxonomies.append("youth")
        if age is not None and age >= 62:
            extra_taxonomies.append("senior")

        # Always include LGBTQ Young Adult — we can't detect this from
        # slots, so include it by default so these services are never
        # invisible to any shelter search.
        extra_taxonomies.append("lgbtq young adult")

        # When user explicitly identified as LGBTQ, trans, or nonbinary,
        # also include sub-categories that may be LGBTQ-affirming
        if gender in ("lgbtq", "transgender", "nonbinary"):
            extra_taxonomies.append("drop-in center")
            extra_taxonomies.append("crisis")

        if extra_taxonomies:
            enriched = list(TEMPLATES["shelter"]["default_params"]["taxonomy_names"])
            enriched.extend(extra_taxonomies)
            user_params["taxonomy_names"] = enriched

    # Co-located service filter: restrict results to locations that also
    # have the additional service types the user asked for.
    colocated_names = []
    if colocated_service_types:
        for co_type in colocated_service_types:
            co_key = resolve_template_key(co_type)
            if co_key and co_key in TEMPLATES:
                co_tax = TEMPLATES[co_key]["default_params"].get("taxonomy_names", [])
                colocated_names.extend(co_tax)
        if colocated_names:
            user_params["colocated_taxonomy_names"] = colocated_names

    result = execute_service_query(
        template_key=template_key,
        user_params=user_params,
        max_results=max_results,
    )

    # If co-located query returned 0 results, retry without the co-location
    # filter so the user still gets results for their primary service.
    if colocated_names and result.get("result_count", 0) == 0:
        user_params.pop("colocated_taxonomy_names", None)
        result = execute_service_query(
            template_key=template_key,
            user_params=user_params,
            max_results=max_results,
        )
        result["colocated_fallback"] = True

    # If co-located types were requested but none could be resolved to
    # taxonomy names (unrecognized service type), mark as fallback so
    # the chatbot doesn't claim co-located results were found.
    if colocated_service_types and not colocated_names:
        result["colocated_fallback"] = True

    return result
