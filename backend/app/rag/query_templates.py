"""
Query Templates — Parameterized SQL for each service category.

Architecture: These are the ONLY queries that touch the Streetlives DB.
Every query is pre-defined, parameterized, and auditable.
The LLM never generates SQL — it only fills slots that feed these templates.

Schema reference (Streetlives PostgreSQL):
    services (3,506 rows)          — id, name, description, fees, organization_id, ...
    locations (2,414 rows)         — id, name, position (PostGIS), organization_id, ...
    service_at_locations (3,405)   — service_id, location_id  (junction)
    taxonomies (39 rows)           — id, name, parent_id, parent_name
    service_taxonomy (3,507)       — service_id, taxonomy_id  (junction)
    eligibility (3,646 rows)       — service_id, parameter_id, eligible_values (JSONB)
    eligibility_parameters (9)     — id, name (gender/age/familySize/income/...)
    physical_addresses (2,569)     — location_id, address_1, city, state_province, postal_code
    regular_schedules (971)        — service_id, weekday, opens_at, closes_at
    organizations (2,460)          — id, name, description, url
    phones (2,730)                 — location_id / service_id / organization_id, number
    accessibility_for_disabilities — location_id, accessibility, details

Key gotchas from schema exploration:
    - NO "borough" column anywhere — use physical_addresses.city
    - NO "type" column on services — use taxonomy junction
    - service_at_locations (with 's') is the active junction table
    - eligibility.eligible_values is JSONB (arrays/objects, varies by param)
    - locations.position is PostGIS USER-DEFINED geometry
"""

from sqlalchemy import text


# ---------------------------------------------------------------------------
# BASE QUERY — shared by all templates
# ---------------------------------------------------------------------------
# This is the common join chain every service query needs. Individual
# templates add WHERE clauses via the `build_query()` function.

_BASE_QUERY = """
SELECT
    s.id              AS service_id,
    s.name            AS service_name,
    s.description     AS service_description,
    s.fees            AS fees,
    s.url             AS service_url,
    s.email           AS service_email,
    s.additional_info AS additional_info,

    o.name            AS organization_name,
    o.url             AS organization_url,

    l.id              AS location_id,
    l.name            AS location_name,
    l.slug            AS location_slug,

    pa.address_1      AS address,
    pa.city           AS city,
    pa.state_province AS state,
    pa.postal_code    AS zip_code,

    best_phone.number     AS phone,

    today_sched.opens_at   AS today_opens,
    today_sched.closes_at  AS today_closes

FROM services s
    JOIN service_taxonomy st       ON s.id = st.service_id
    JOIN taxonomies t              ON st.taxonomy_id = t.id
    JOIN service_at_locations sal  ON s.id = sal.service_id
    JOIN locations l               ON sal.location_id = l.id
    LEFT JOIN organizations o      ON s.organization_id = o.id
    LEFT JOIN physical_addresses pa ON l.id = pa.location_id
    LEFT JOIN LATERAL (
        SELECT ph.number
        FROM phones ph
        WHERE ph.location_id = l.id
           OR ph.service_id = s.id
           OR ph.organization_id = o.id
        ORDER BY
            CASE
                WHEN ph.location_id = l.id THEN 1
                WHEN ph.service_id = s.id THEN 2
                WHEN ph.organization_id = o.id THEN 3
            END
        LIMIT 1
    ) best_phone ON TRUE
    LEFT JOIN LATERAL (
        SELECT rs.opens_at, rs.closes_at
        FROM regular_schedules rs
        WHERE rs.service_id = s.id
          AND rs.weekday = EXTRACT(ISODOW FROM CURRENT_DATE)::int - 1
        LIMIT 1
    ) today_sched ON TRUE
"""

# ---------------------------------------------------------------------------
# FILTER FRAGMENTS — composable WHERE/AND clauses
# ---------------------------------------------------------------------------
# Each fragment is a tuple of (sql_clause, required_param_keys).
# The query builder picks only the fragments whose params are present.

FILTER_BY_TAXONOMY_NAME = (
    "LOWER(t.name) = LOWER(:taxonomy_name)",
    ["taxonomy_name"],
)

FILTER_BY_CITY = (
    "LOWER(pa.city) = LOWER(:city)",
    ["city"],
)

# Borough-level city match — matches any city value that belongs to the borough.
# When a user says "Queens", this matches "Queens", "Astoria", "Flushing",
# "Jamaica", "Long Island City", etc.
# The SQL uses ANY() with an array parameter, which SQLAlchemy handles natively.
FILTER_BY_CITY_IN_BOROUGH = (
    "LOWER(pa.city) = ANY(:city_list)",
    ["city_list"],
)

# Broader city match — matches if the city field contains the search term.
# Useful because some addresses store "East New York" not "Brooklyn".
FILTER_BY_CITY_LIKE = (
    "LOWER(pa.city) LIKE LOWER(:city_pattern)",
    ["city_pattern"],
)

# State filter — ensures results are within New York State.
# Prevents results from Poughkeepsie, Albany, etc. leaking in when
# the city filter is relaxed.
FILTER_BY_STATE_NY = (
    "LOWER(pa.state_province) = 'ny'",
    [],
)

# PostGIS proximity search (requires lat/lon).
# Returns services within :radius_meters of the given point.
FILTER_BY_PROXIMITY = (
    "ST_DWithin(l.position::geography, ST_MakePoint(:lon, :lat)::geography, :radius_meters)",
    ["lat", "lon", "radius_meters"],
)

# Age eligibility — checks the JSONB eligible_values for age ranges.
# A service matches if:
#   - It has no age eligibility rule (open to all), OR
#   - Its age rule includes all_ages = true, OR
#   - The user's age falls within [age_min, age_max]
FILTER_BY_AGE_ELIGIBILITY = (
    """
    NOT EXISTS (
        SELECT 1 FROM eligibility e
        JOIN eligibility_parameters ep ON e.parameter_id = ep.id
        WHERE e.service_id = s.id
          AND ep.name = 'age'
          AND NOT (
              e.eligible_values @> '[{"all_ages": true}]'::jsonb
              OR (
                  (e.eligible_values->0->>'age_min' IS NULL
                   OR (e.eligible_values->0->>'age_min')::int <= :age)
                  AND
                  (e.eligible_values->0->>'age_max' IS NULL
                   OR (e.eligible_values->0->>'age_max')::int >= :age)
              )
          )
    )
    """,
    ["age"],
)

# Gender eligibility — checks if the service accepts the user's gender.
# A service matches if:
#   - It has no gender eligibility rule, OR
#   - Its eligible_values array contains the user's gender
FILTER_BY_GENDER_ELIGIBILITY = (
    """
    NOT EXISTS (
        SELECT 1 FROM eligibility e
        JOIN eligibility_parameters ep ON e.parameter_id = ep.id
        WHERE e.service_id = s.id
          AND ep.name = 'gender'
          AND NOT e.eligible_values @> to_jsonb(:gender::text)
    )
    """,
    ["gender"],
)

# Schedule filter — only services open on a given weekday.
# weekday: 0=Monday … 6=Sunday (matches regular_schedules.weekday)
FILTER_BY_WEEKDAY = (
    """
    EXISTS (
        SELECT 1 FROM regular_schedules rs
        WHERE rs.service_id = s.id
          AND rs.weekday = :weekday
    )
    """,
    ["weekday"],
)

# Schedule filter — services open at a specific time on a given weekday.
FILTER_BY_OPEN_NOW = (
    """
    EXISTS (
        SELECT 1 FROM regular_schedules rs
        WHERE rs.service_id = s.id
          AND rs.weekday = :weekday
          AND rs.opens_at <= :current_time
          AND rs.closes_at >= :current_time
    )
    """,
    ["weekday", "current_time"],
)

# Exclude services hidden from search
FILTER_NOT_HIDDEN = (
    "l.hidden_from_search IS NOT TRUE",
    [],
)

# ---------------------------------------------------------------------------
# ORDER + LIMIT
# ---------------------------------------------------------------------------
_ORDER_LIMIT = """
ORDER BY o.name, s.name
LIMIT :max_results
"""

_DEFAULT_MAX_RESULTS = 10


# ---------------------------------------------------------------------------
# TEMPLATE DEFINITIONS
# ---------------------------------------------------------------------------
# Each template specifies which filters are always applied and which are
# conditional (applied only if the user provided that slot).

TEMPLATES = {
    "food": {
        "name": "FoodQuery",
        "description": "Find food services (pantries, soup kitchens, meals) by location",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
            FILTER_BY_GENDER_ELIGIBILITY,
            FILTER_BY_WEEKDAY,
            FILTER_BY_OPEN_NOW,
        ],
        "default_params": {"taxonomy_name": "Food"},
        "taxonomy_aliases": [
            "Food", "Food Pantry", "Mobile Pantry", "Mobile Market",
            "Mobile Soup Kitchen", "Brown Bag", "Farmer's Markets",
        ],
    },
    "shelter": {
        "name": "HousingEligibilityQuery",
        "description": "Find shelters and housing with eligibility checks",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
            FILTER_BY_GENDER_ELIGIBILITY,
            FILTER_BY_WEEKDAY,
        ],
        "default_params": {"taxonomy_name": "Shelter"},
        "taxonomy_aliases": ["Shelter"],
    },
    "clothing": {
        "name": "ClothingQuery",
        "description": "Find clothing distribution services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
            FILTER_BY_GENDER_ELIGIBILITY,
        ],
        "default_params": {"taxonomy_name": "Clothing"},
        "taxonomy_aliases": ["Clothing"],
    },
    "medical": {
        "name": "HealthcareQuery",
        "description": "Find medical and healthcare services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
        ],
        "default_params": {"taxonomy_name": "Health"},
        "taxonomy_aliases": ["Health", "Crisis"],
    },
    "legal": {
        "name": "LegalQuery",
        "description": "Find legal aid and immigration services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
        ],
        "default_params": {"taxonomy_name": "Legal Services"},
        "taxonomy_aliases": ["Legal Services", "Advocates / Legal Aid"],
    },
    "employment": {
        "name": "EmploymentQuery",
        "description": "Find job training and employment services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
        ],
        "default_params": {"taxonomy_name": "Employment"},
        "taxonomy_aliases": ["Employment"],
    },
    "personal_care": {
        "name": "PersonalCareQuery",
        "description": "Find showers, laundry, toiletries, and hygiene services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_GENDER_ELIGIBILITY,
            FILTER_BY_WEEKDAY,
        ],
        "default_params": {"taxonomy_name": "Personal Care"},
        "taxonomy_aliases": ["Personal Care", "Shower", "Laundry", "Toiletries"],
    },
    "mental_health": {
        "name": "MentalHealthQuery",
        "description": "Find mental health, counseling, and substance abuse services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
            FILTER_BY_AGE_ELIGIBILITY,
        ],
        "default_params": {"taxonomy_name": "Mental Health"},
        "taxonomy_aliases": ["Mental Health"],
    },
    "other": {
        "name": "OtherServicesQuery",
        "description": "Find benefits, IDs, mail, phone, and miscellaneous services",
        "required_filters": [FILTER_BY_TAXONOMY_NAME, FILTER_NOT_HIDDEN, FILTER_BY_STATE_NY],
        "optional_filters": [
            FILTER_BY_CITY,
            FILTER_BY_CITY_IN_BOROUGH,
            FILTER_BY_CITY_LIKE,
            FILTER_BY_PROXIMITY,
        ],
        "default_params": {"taxonomy_name": "Other service"},
        "taxonomy_aliases": ["Other service"],
    },
}


# ---------------------------------------------------------------------------
# QUERY BUILDER
# ---------------------------------------------------------------------------

def build_query(template_key: str, user_params: dict) -> tuple[str, dict]:
    """
    Assemble a parameterized SQL query from a template and user-provided slots.

    Args:
        template_key: One of the keys in TEMPLATES (e.g. "food", "shelter")
        user_params:  Dict of slot values from the intake form, e.g.
                      {"city": "Brooklyn", "age": 17, "gender": "male"}

    Returns:
        (sql_string, bound_params) ready for SQLAlchemy text() execution.

    Raises:
        ValueError: If template_key is not recognized.
    """
    if template_key not in TEMPLATES:
        raise ValueError(
            f"Unknown template '{template_key}'. "
            f"Valid templates: {list(TEMPLATES.keys())}"
        )

    template = TEMPLATES[template_key]

    # Start with default params, then overlay user params
    params = dict(template["default_params"])
    params.update({k: v for k, v in user_params.items() if v is not None})

    # Collect WHERE clauses
    where_clauses = []

    # Required filters — always applied
    for sql_fragment, required_keys in template["required_filters"]:
        where_clauses.append(sql_fragment)

    # Optional filters — only applied if user provided the required params
    for sql_fragment, required_keys in template["optional_filters"]:
        if all(k in params for k in required_keys):
            where_clauses.append(sql_fragment)

    # Assemble the full query
    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # Set max_results default
    if "max_results" not in params:
        params["max_results"] = _DEFAULT_MAX_RESULTS

    full_sql = f"{_BASE_QUERY}\nWHERE {where_sql}\n{_ORDER_LIMIT}"

    return full_sql, params


def build_relaxed_query(template_key: str, user_params: dict) -> tuple[str, dict]:
    """
    Build a relaxed version of the query for when the strict version
    returns zero results. Drops filters progressively but KEEPS location
    boundaries to prevent out-of-area results:

    1. Drop time/schedule filters
    2. Drop eligibility filters (age, gender)
    3. Broaden city match:
       - Neighborhood search: promote _borough_city_list → city_list
         (exact "Harlem" → all Manhattan neighborhoods)
       - Borough search: keep existing city_list
       - No expansion available: exact city → LIKE pattern
    4. State filter (NY) is NEVER dropped

    Returns the broadest reasonable query. Caller should note to the user
    that results may be less precisely matched.
    """
    relaxed_params = dict(user_params)

    # Remove schedule-related params
    for key in ["weekday", "current_time"]:
        relaxed_params.pop(key, None)

    # Remove eligibility params
    for key in ["age", "gender"]:
        relaxed_params.pop(key, None)

    # Promote _borough_city_list (from neighborhood searches) to city_list
    # so the relaxed query broadens from "Harlem" to all of Manhattan.
    if "_borough_city_list" in relaxed_params:
        relaxed_params["city_list"] = relaxed_params.pop("_borough_city_list")
        relaxed_params.pop("city", None)
    elif "city_list" in relaxed_params:
        # Borough expansion already covers neighborhoods — drop exact match
        relaxed_params.pop("city", None)
    elif "city" in relaxed_params:
        # No expansion available — broaden to LIKE
        city = relaxed_params.pop("city")
        relaxed_params["city_pattern"] = f"%{city}%"

    return build_query(template_key, relaxed_params)


# ---------------------------------------------------------------------------
# RESULT FORMATTER
# ---------------------------------------------------------------------------

def format_service_card(row: dict) -> dict:
    """
    Format a raw query result row into a structured service card.

    This is the ONLY place service data is assembled for display.
    No LLM synthesis — just field mapping.
    """
    # Build address string
    address_parts = [
        row.get("address"),
        row.get("city"),
        row.get("state"),
        row.get("zip_code"),
    ]
    full_address = ", ".join(p for p in address_parts if p)

    # Build YourPeer listing URL from location slug
    slug = row.get("location_slug")
    yourpeer_url = f"https://yourpeer.nyc/locations/{slug}" if slug else None

    # Build schedule / open status
    today_opens = row.get("today_opens")
    today_closes = row.get("today_closes")
    schedule_status = _compute_schedule_status(today_opens, today_closes)

    return {
        "service_id": str(row.get("service_id", "")),
        "service_name": row.get("service_name") or "Unknown Service",
        "organization": row.get("organization_name"),
        "description": row.get("service_description"),
        "address": full_address or None,
        "city": row.get("city"),
        "phone": row.get("phone"),
        "email": row.get("service_email"),
        "website": row.get("service_url") or row.get("organization_url"),
        "fees": row.get("fees"),
        "additional_info": row.get("additional_info"),
        "yourpeer_url": yourpeer_url,
        "hours_today": schedule_status["hours_today"],
        "is_open": schedule_status["is_open"],
    }


def _compute_schedule_status(opens_at, closes_at) -> dict:
    """
    Compute human-readable hours and open/closed status.

    Returns:
        {
            "hours_today": str or None,
                e.g. "9:00 AM – 5:00 PM", or None if no data
            "is_open": "open" | "closed" | None
                None means no schedule data available
        }
    """
    if opens_at is None or closes_at is None:
        return {"hours_today": None, "is_open": None}

    from datetime import datetime, time as dt_time

    # Parse the opens_at / closes_at values.
    # They come from the DB as time strings (HH:MM:SS) or time objects.
    try:
        if isinstance(opens_at, str):
            open_time = datetime.strptime(opens_at.strip(), "%H:%M:%S").time()
        elif isinstance(opens_at, dt_time):
            open_time = opens_at
        else:
            open_time = datetime.strptime(str(opens_at).strip()[:8], "%H:%M:%S").time()

        if isinstance(closes_at, str):
            close_time = datetime.strptime(closes_at.strip(), "%H:%M:%S").time()
        elif isinstance(closes_at, dt_time):
            close_time = closes_at
        else:
            close_time = datetime.strptime(str(closes_at).strip()[:8], "%H:%M:%S").time()
    except (ValueError, AttributeError):
        return {"hours_today": None, "is_open": None}

    # Format for display
    open_str = _format_time(open_time)
    close_str = _format_time(close_time)
    hours_today = f"{open_str} – {close_str}"

    # Determine if currently open
    now = datetime.now().time()
    if open_time <= close_time:
        is_open = "open" if open_time <= now <= close_time else "closed"
    else:
        # Wraps midnight (e.g. 8 PM – 6 AM)
        is_open = "open" if now >= open_time or now <= close_time else "closed"

    return {"hours_today": hours_today, "is_open": is_open}


def _format_time(t) -> str:
    """Format a time object as '9:00 AM' style (cross-platform)."""
    from datetime import datetime
    # Use %I (zero-padded) then strip the leading zero manually.
    # %-I is macOS-only and crashes on Linux.
    formatted = datetime.combine(datetime.min, t).strftime("%I:%M %p")
    return formatted.lstrip("0") if formatted.startswith("0") else formatted


def deduplicate_results(rows: list[dict]) -> list[dict]:
    """
    Remove duplicate service cards (same service can appear multiple times
    due to multiple phone numbers or addresses from the LEFT JOINs).

    Keep the first occurrence of each service_id.
    """
    seen = set()
    unique = []
    for row in rows:
        sid = row.get("service_id")
        if sid and sid not in seen:
            seen.add(sid)
            unique.append(row)
    return unique
