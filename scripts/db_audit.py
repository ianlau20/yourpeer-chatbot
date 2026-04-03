"""
YourPeer DB Audit Script
========================
Run this against any environment (staging or production) to validate
that the application's query templates and chat logic match the actual
database content.

Usage:
    DATABASE_URL=postgresql://... python scripts/db_audit.py
    DATABASE_URL=postgresql://... python scripts/db_audit.py --section taxonomy
    DATABASE_URL=postgresql://... python scripts/db_audit.py --output audit_report.md

Sections:
    taxonomy     — Taxonomy name coverage per service category
    borough      — Service distribution by borough (informs no-result messages)
    hidden       — Hidden service counts by taxonomy
    schedule     — Schedule data coverage (informs open-now filter decisions)
    phone        — Phone number coverage by taxonomy
    eligibility  — Eligibility rule types and coverage
    freshness    — last_validated_at distribution
    description  — Description field coverage
    names        — Service name length and quality checks
    membership   — Membership/referral eligibility value distribution

Each section prints a summary and flags any items requiring action.

Exit codes:
    0 — all checks passed
    1 — one or more action items found
"""

import os
import sys
import argparse
from datetime import datetime

try:
    from sqlalchemy import create_engine, text
except ImportError:
    print("ERROR: sqlalchemy not installed. Run: pip install sqlalchemy psycopg2-binary")
    sys.exit(1)


# ---------------------------------------------------------------------------
# CONNECTION
# ---------------------------------------------------------------------------

def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable not set.")
        print("Usage: DATABASE_URL=postgresql://... python scripts/db_audit.py")
        sys.exit(1)
    return create_engine(url, echo=False)


def run_query(engine, sql: str) -> list[dict]:
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        return [dict(zip(cols, row)) for row in result.fetchall()]


# ---------------------------------------------------------------------------
# FORMATTING HELPERS
# ---------------------------------------------------------------------------

def hr(char="─", width=70):
    return char * width

def header(title: str):
    print(f"\n{hr('═')}")
    print(f"  {title}")
    print(hr('═'))

def section(title: str):
    print(f"\n{hr()}")
    print(f"  {title}")
    print(hr())

def flag(msg: str):
    print(f"  ⚠️  ACTION: {msg}")

def ok(msg: str):
    print(f"  ✓  {msg}")

def info(msg: str):
    print(f"     {msg}")

def table(rows: list[dict], cols: list[str] = None, max_col_width: int = 40):
    if not rows:
        print("     (no rows)")
        return
    cols = cols or list(rows[0].keys())
    widths = {c: max(len(str(c)), max(len(str(r.get(c, "")))[:max_col_width] for r in rows)) for c in cols}
    header_row = "  " + "  ".join(str(c).ljust(widths[c]) for c in cols)
    print(header_row)
    print("  " + "  ".join("─" * widths[c] for c in cols))
    for row in rows:
        print("  " + "  ".join(str(row.get(c, ""))[:max_col_width].ljust(widths[c]) for c in cols))


# ---------------------------------------------------------------------------
# KNOWN GOOD TAXONOMY NAMES
# From staging DB audit April 2026. Update after running on prod.
# ---------------------------------------------------------------------------

KNOWN_TAXONOMY_NAMES = {
    "Food", "Food Pantry", "Food Benefits", "Mobile Pantry", "Mobile Food Truck",
    "Mobile Market", "Food Delivery / Meals on Wheels", "Soup Kitchen",
    "Mobile Soup Kitchen", "Brown Bag", "Farmer's Markets",
    "Shelter", "Transitional Independent Living (TIL)", "Supportive Housing",
    "Housing Lottery", "Veterans Short-Term Housing", "Warming Center", "Safe Haven",
    "Clothing", "Clothing Pantry", "Interview-Ready Clothing", "Professional Clothing",
    "Coat Drive", "Thrift Shop",
    "Health", "General Health", "Crisis",
    "Mental Health", "Substance Use Treatment", "Residential Recovery", "Support Groups",
    "Legal Services", "Immigration Services",
    "Employment", "Internship",
    "Personal Care", "Shower", "Laundry", "Toiletries", "Hygiene", "Haircut", "Restrooms",
    "Other service", "Benefits", "Drop-in Center", "Case Workers", "Referral",
    "Education", "Mail", "Free Wifi", "Taxes", "Baby Supplies", "Baby", "Assessment",
    "Community Services", "Activities", "Appliances", "Gym", "Pets", "Single Adult",
    "Families", "Youth", "Senior", "Veterans", "LGBTQ Young Adult", "Intake",
    "Soup Kitchen", "Mobile Soup Kitchen", "Brown Bag",
}

# Template taxonomy_names from query_templates.py (lowercased)
TEMPLATE_TAXONOMY_NAMES = {
    "food": {
        "food", "food pantry", "food benefits", "mobile pantry", "mobile food truck",
        "mobile market", "food delivery / meals on wheels", "soup kitchen",
        "mobile soup kitchen", "brown bag", "farmer's markets",
    },
    "shelter": {
        "shelter", "transitional independent living (til)", "supportive housing",
        "housing lottery", "veterans short-term housing", "warming center", "safe haven",
    },
    "clothing": {
        "clothing", "clothing pantry", "interview-ready clothing", "professional clothing",
        "coat drive", "thrift shop",
    },
    "medical": {"health", "general health", "crisis"},
    "legal": {"legal services", "immigration services"},
    "employment": {"employment", "internship"},
    "personal_care": {
        "personal care", "shower", "laundry", "toiletries", "hygiene", "haircut", "restrooms",
    },
    "mental_health": {
        "mental health", "substance use treatment", "residential recovery", "support groups",
    },
    "other": {
        "other service", "benefits", "drop-in center", "case workers", "referral",
        "education", "mail", "free wifi", "taxes", "baby supplies", "baby", "assessment",
        "community services", "activities", "appliances", "gym", "pets", "single adult",
        "families", "youth", "senior", "veterans", "lgbtq young adult", "intake",
    },
}

ALL_TEMPLATE_NAMES = {name for names in TEMPLATE_TAXONOMY_NAMES.values() for name in names}


# ---------------------------------------------------------------------------
# AUDIT SECTIONS
# ---------------------------------------------------------------------------

def audit_taxonomy(engine) -> list[str]:
    """Check what taxonomy names exist in the DB and flag any not covered by templates."""
    section("TAXONOMY COVERAGE")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy_name,
               COUNT(*) AS service_count
        FROM taxonomies t
        JOIN service_taxonomy st ON st.taxonomy_id = t.id
        GROUP BY t.name
        ORDER BY service_count DESC
    """)

    new_names = []
    unmatched_significant = []

    for row in rows:
        name = row["taxonomy_name"]
        count = row["service_count"]
        matched = name.lower() in ALL_TEMPLATE_NAMES
        is_new = name not in KNOWN_TAXONOMY_NAMES

        status = "✓" if matched else "✗"
        new_tag = " [NEW]" if is_new else ""
        print(f"  {status}  {name:<45} {count:>5} services{new_tag}")

        if is_new:
            new_names.append((name, count))
        if not matched and count >= 5:
            unmatched_significant.append((name, count))

    if new_names:
        print()
        flag(f"{len(new_names)} taxonomy name(s) not seen in staging — verify they are covered:")
        for name, count in sorted(new_names, key=lambda x: -x[1]):
            info(f"{name} ({count} services)")
        action_items.append(f"New taxonomy names found: {[n for n, _ in new_names]}")

    if unmatched_significant:
        print()
        flag(f"{len(unmatched_significant)} significant taxonomy name(s) not matched by any template:")
        for name, count in sorted(unmatched_significant, key=lambda x: -x[1]):
            info(f"{name} ({count} services) — add to appropriate template's taxonomy_names list")
        action_items.append(f"Unmatched significant taxonomies: {[n for n, _ in unmatched_significant]}")

    if not new_names and not unmatched_significant:
        ok("All taxonomy names are covered by templates")

    return action_items


def audit_borough(engine) -> list[str]:
    """Check service distribution by borough and taxonomy — informs no-result messages."""
    section("BOROUGH DISTRIBUTION BY TAXONOMY")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy, pa.borough, COUNT(*) AS services
        FROM services s
        JOIN service_taxonomy st ON st.service_id = s.id
        JOIN taxonomies t ON t.id = st.taxonomy_id
        JOIN service_at_locations sal ON sal.service_id = s.id
        JOIN locations l ON l.id = sal.location_id
        LEFT JOIN physical_addresses pa ON pa.location_id = l.id
        WHERE pa.borough IS NOT NULL
          AND t.name IN (
            'Food Pantry', 'Soup Kitchen', 'Shelter', 'Clothing Pantry',
            'Mental Health', 'Health', 'Legal Services', 'Employment', 'Shower'
          )
        GROUP BY t.name, pa.borough
        ORDER BY t.name, services DESC
    """)

    table(rows, ["taxonomy", "borough", "services"])

    # Flag thin boroughs (< 5 services in any key category)
    thin = [(r["taxonomy"], r["borough"], r["services"]) for r in rows if r["services"] < 5]
    if thin:
        print()
        flag("Borough + category combinations with fewer than 5 services (high no-result risk):")
        for taxonomy, borough, count in sorted(thin, key=lambda x: x[2]):
            info(f"{borough} — {taxonomy}: {count} service(s)")
        info("Review chatbot.py _NEARBY_BOROUGHS_BY_SERVICE against this data")
        action_items.append(f"Thin borough/category combinations: {[(t, b) for t, b, _ in thin]}")
    else:
        ok("No borough + category combinations with critically low service counts")

    return action_items


def audit_hidden(engine) -> list[str]:
    """Check how many services are hidden from search by taxonomy."""
    section("HIDDEN SERVICES BY TAXONOMY")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy,
               COUNT(*) FILTER (WHERE l.hidden_from_search = true) AS hidden,
               COUNT(*) FILTER (WHERE l.hidden_from_search IS NOT TRUE) AS visible,
               COUNT(*) AS total
        FROM services s
        JOIN service_taxonomy st ON st.service_id = s.id
        JOIN taxonomies t ON t.id = st.taxonomy_id
        JOIN service_at_locations sal ON sal.service_id = s.id
        JOIN locations l ON l.id = sal.location_id
        GROUP BY t.name
        HAVING COUNT(*) FILTER (WHERE l.hidden_from_search = true) > 0
        ORDER BY hidden DESC
    """)

    if not rows:
        ok("No hidden services found — FILTER_NOT_HIDDEN has no impact")
    else:
        table(rows, ["taxonomy", "hidden", "visible", "total"])
        high_hidden = [r for r in rows if r["hidden"] / r["total"] > 0.1]
        if high_hidden:
            print()
            flag("Taxonomies with >10% hidden services:")
            for r in high_hidden:
                pct = round(r["hidden"] / r["total"] * 100)
                info(f"{r['taxonomy']}: {r['hidden']}/{r['total']} ({pct}%) hidden")
            action_items.append("High hidden service rate — investigate why services are hidden")

    return action_items


def audit_schedule(engine) -> list[str]:
    """Check schedule data coverage — informs whether open-now filters are usable."""
    section("SCHEDULE COVERAGE BY TAXONOMY")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy,
               COUNT(*) AS total,
               COUNT(rs.id) AS with_schedule,
               COUNT(*) - COUNT(rs.id) AS no_schedule,
               ROUND((COUNT(rs.id)) * 100.0 / COUNT(*), 0) AS pct_with_schedule
        FROM services s
        JOIN service_taxonomy st ON st.service_id = s.id
        JOIN taxonomies t ON t.id = st.taxonomy_id
        LEFT JOIN regular_schedules rs ON rs.service_id = s.id
        GROUP BY t.name
        HAVING COUNT(*) >= 5
        ORDER BY pct_with_schedule DESC, total DESC
    """)

    table(rows, ["taxonomy", "total", "with_schedule", "no_schedule", "pct_with_schedule"])

    # Check if schedule coverage has improved enough to re-enable open-now filters
    high_coverage = [r for r in rows if int(r["pct_with_schedule"]) >= 60 and r["total"] >= 10]
    if high_coverage:
        print()
        info("Taxonomies with ≥60% schedule coverage (open-now filtering may be viable):")
        for r in high_coverage:
            info(f"  {r['taxonomy']}: {r['pct_with_schedule']}%")
        if len(high_coverage) >= 3:
            flag("Schedule coverage has improved — consider re-enabling FILTER_BY_OPEN_NOW")
            action_items.append("Schedule coverage improved — evaluate enabling open-now filter")
    else:
        ok("Schedule coverage still sparse — FILTER_BY_OPEN_NOW correctly kept dormant")

    return action_items


def audit_phone(engine) -> list[str]:
    """Check phone number coverage by taxonomy."""
    section("PHONE COVERAGE BY TAXONOMY")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy,
               COUNT(*) AS total,
               COUNT(ph.id) AS with_phone,
               COUNT(*) - COUNT(ph.id) AS no_phone,
               ROUND((COUNT(*) - COUNT(ph.id)) * 100.0 / COUNT(*), 0) AS pct_no_phone
        FROM services s
        JOIN service_taxonomy st ON st.service_id = s.id
        JOIN taxonomies t ON t.id = st.taxonomy_id
        LEFT JOIN phones ph ON ph.service_id = s.id
        GROUP BY t.name
        HAVING COUNT(*) - COUNT(ph.id) > 0
        ORDER BY pct_no_phone DESC, total DESC
        LIMIT 20
    """)

    if not rows:
        ok("100% phone coverage across all taxonomies")
    else:
        table(rows, ["taxonomy", "total", "with_phone", "no_phone", "pct_no_phone"])
        high_missing = [r for r in rows if int(r["pct_no_phone"]) >= 20 and r["total"] >= 10]
        if high_missing:
            print()
            flag("Taxonomies with ≥20% missing phone numbers (Call button will be absent):")
            for r in high_missing:
                info(f"{r['taxonomy']}: {r['no_phone']}/{r['total']} missing")
            action_items.append("Significant phone coverage gaps found")

    return action_items


def audit_eligibility(engine) -> list[str]:
    """Check eligibility rule types and coverage."""
    section("ELIGIBILITY RULE COVERAGE")
    action_items = []

    rows = run_query(engine, """
        SELECT ep.name AS parameter,
               COUNT(DISTINCT e.service_id) AS services_with_rule
        FROM eligibility e
        JOIN eligibility_parameters ep ON ep.id = e.parameter_id
        GROUP BY ep.name
        ORDER BY services_with_rule DESC
    """)

    table(rows, ["parameter", "services_with_rule"])

    # Check for new eligibility parameter types we don't handle
    known_params = {"age", "gender", "membership", "general", "languageSpoken", "familySize", "orientation"}
    new_params = [r for r in rows if r["parameter"] not in known_params and r["services_with_rule"] >= 10]
    if new_params:
        print()
        flag("New eligibility parameter types with ≥10 services — may need filter support:")
        for r in new_params:
            info(f"{r['parameter']}: {r['services_with_rule']} services")
        action_items.append(f"New eligibility parameters: {[r['parameter'] for r in new_params]}")
    else:
        ok("No new significant eligibility parameter types found")

    # Check membership values
    membership_rows = run_query(engine, """
        SELECT e.eligible_values::text AS values, COUNT(*) AS services
        FROM eligibility e
        JOIN eligibility_parameters ep ON ep.id = e.parameter_id
        WHERE ep.name = 'membership'
        GROUP BY e.eligible_values::text
        ORDER BY services DESC
    """)

    if membership_rows:
        print()
        info("Membership eligibility distribution (affects 'Referral may be required' badge):")
        for r in membership_rows:
            info(f"  {r['values']}: {r['services']} services")

    return action_items


def audit_freshness(engine) -> list[str]:
    """Check last_validated_at distribution against the ≥80% freshness target."""
    section("DATA FRESHNESS (last_validated_at)")
    action_items = []

    rows = run_query(engine, """
        SELECT
          CASE
            WHEN l.last_validated_at >= NOW() - INTERVAL '90 days'  THEN 'fresh (< 90 days)'
            WHEN l.last_validated_at >= NOW() - INTERVAL '180 days' THEN 'stale (90–180 days)'
            WHEN l.last_validated_at >= NOW() - INTERVAL '365 days' THEN 'old (180–365 days)'
            WHEN l.last_validated_at IS NULL                         THEN 'never validated'
            ELSE 'very old (> 1 year)'
          END AS freshness,
          COUNT(*) AS locations,
          ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM locations l
        GROUP BY 1
        ORDER BY locations DESC
    """)

    table(rows, ["freshness", "locations", "pct"])

    fresh_pct = next((float(r["pct"]) for r in rows if "< 90 days" in r["freshness"]), 0.0)
    target = 80.0

    print()
    if fresh_pct >= target:
        ok(f"Freshness target met: {fresh_pct}% fresh (target ≥{target}%)")
    else:
        flag(f"Freshness target MISSED: {fresh_pct}% fresh (target ≥{target}%)")
        info("Consider surfacing last_validated_at on service cards or alerting data stewards")
        action_items.append(f"Freshness below target: {fresh_pct}% vs ≥{target}% goal")

    return action_items


def audit_description(engine) -> list[str]:
    """Check description field coverage — informs card UX expectations."""
    section("DESCRIPTION COVERAGE BY TAXONOMY")
    action_items = []

    rows = run_query(engine, """
        SELECT t.name AS taxonomy,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE s.description IS NULL OR TRIM(s.description) = '') AS no_description,
               ROUND(COUNT(*) FILTER (WHERE s.description IS NULL OR TRIM(s.description) = '')
                     * 100.0 / COUNT(*), 0) AS pct_no_description
        FROM services s
        JOIN service_taxonomy st ON st.service_id = s.id
        JOIN taxonomies t ON t.id = st.taxonomy_id
        GROUP BY t.name
        HAVING COUNT(*) >= 5
        ORDER BY pct_no_description DESC, total DESC
    """)

    table(rows, ["taxonomy", "total", "no_description", "pct_no_description"])

    overall_missing = sum(r["no_description"] for r in rows)
    overall_total = sum(r["total"] for r in rows)
    overall_pct = round(overall_missing / overall_total * 100) if overall_total else 0

    print()
    info(f"Overall: {overall_missing}/{overall_total} services missing description ({overall_pct}%)")
    if overall_pct > 60:
        ok("High description absence is expected — card renders name/address/phone without it")

    return action_items


def audit_names(engine) -> list[str]:
    """Check service name quality."""
    section("SERVICE NAME QUALITY")
    action_items = []

    # Null or generic names
    generic_rows = run_query(engine, """
        SELECT s.name, COUNT(*) as count
        FROM services s
        WHERE s.name IS NULL
           OR TRIM(s.name) = ''
           OR LOWER(s.name) IN ('services', 'service', 'programs', 'program', 'other')
        GROUP BY s.name
        ORDER BY count DESC
    """)

    if generic_rows:
        flag(f"{sum(r['count'] for r in generic_rows)} services with null or generic names:")
        table(generic_rows, ["name", "count"])
        action_items.append("Generic/null service names found — card titles will be unhelpful")
    else:
        ok("No null or generic service names")

    # Name length stats
    length_rows = run_query(engine, """
        SELECT MAX(LENGTH(s.name)) AS max_length,
               ROUND(AVG(LENGTH(s.name))) AS avg_length,
               COUNT(*) FILTER (WHERE LENGTH(s.name) > 80) AS over_80_chars
        FROM services s
        WHERE s.name IS NOT NULL
    """)

    if length_rows:
        r = length_rows[0]
        info(f"Name lengths — max: {r['max_length']}, avg: {r['avg_length']}, over 80 chars: {r['over_80_chars']}")
        if r["over_80_chars"] and int(r["over_80_chars"]) > 10:
            flag(f"{r['over_80_chars']} service names exceed 80 characters — may affect card layout")
            action_items.append("Many long service names — review card truncation")

    return action_items


def audit_membership(engine) -> list[str]:
    """Detailed membership eligibility breakdown."""
    section("MEMBERSHIP / REFERRAL ELIGIBILITY")
    action_items = []

    rows = run_query(engine, """
        SELECT e.eligible_values::text AS eligible_values,
               COUNT(*) AS services
        FROM eligibility e
        JOIN eligibility_parameters ep ON ep.id = e.parameter_id
        WHERE ep.name = 'membership'
        GROUP BY e.eligible_values::text
        ORDER BY services DESC
    """)

    table(rows, ["eligible_values", "services"])

    referral_required = sum(
        r["services"] for r in rows
        if r["eligible_values"] in ('["true"]', '[true]')
    )
    open_to_all = sum(
        r["services"] for r in rows
        if r["eligible_values"] in ('["true", "false"]', '["false", "true"]', '[true, false]', '[false, true]')
    )

    print()
    info(f"Services showing 'Referral may be required' badge: {referral_required}")
    info(f"Services open to members and non-members (no badge): {open_to_all}")

    if referral_required > 1000:
        flag(f"High referral count ({referral_required}) — consider surfacing this more prominently in chat")
        action_items.append(f"High referral-required count: {referral_required} services")
    else:
        ok(f"Referral badge will appear on {referral_required} services")

    return action_items


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

SECTIONS = {
    "taxonomy":    (audit_taxonomy,    "Taxonomy coverage — are all DB names matched by templates?"),
    "borough":     (audit_borough,     "Borough distribution — informs no-result suggestions"),
    "hidden":      (audit_hidden,      "Hidden services — impact of FILTER_NOT_HIDDEN"),
    "schedule":    (audit_schedule,    "Schedule coverage — should open-now filters be enabled?"),
    "phone":       (audit_phone,       "Phone coverage — will Call button appear?"),
    "eligibility": (audit_eligibility, "Eligibility rules — any new parameter types?"),
    "freshness":   (audit_freshness,   "Data freshness — is ≥80% target met?"),
    "description": (audit_description, "Description coverage — card UX expectations"),
    "names":       (audit_names,       "Service name quality"),
    "membership":  (audit_membership,  "Membership/referral badge distribution"),
}


def main():
    parser = argparse.ArgumentParser(description="YourPeer DB audit script")
    parser.add_argument(
        "--section", "-s",
        choices=list(SECTIONS.keys()),
        default=None,
        help="Run a specific section only (default: all)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save output to a file (in addition to stdout)",
    )
    args = parser.parse_args()

    # Optionally tee output to a file
    if args.output:
        import io
        buffer = io.StringIO()
        original_stdout = sys.stdout

        class Tee:
            def write(self, s):
                original_stdout.write(s)
                buffer.write(s)
            def flush(self):
                original_stdout.flush()

        sys.stdout = Tee()

    engine = get_engine()

    header(f"YourPeer DB Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Database: {os.getenv('DATABASE_URL', '').split('@')[-1]}")  # hide credentials

    all_action_items = []

    sections_to_run = (
        {args.section: SECTIONS[args.section]}
        if args.section
        else SECTIONS
    )

    for key, (fn, description) in sections_to_run.items():
        try:
            items = fn(engine)
            all_action_items.extend(items)
        except Exception as e:
            print(f"\n  ❌ Section '{key}' failed: {e}")
            all_action_items.append(f"Section '{key}' error: {e}")

    # Summary
    header("SUMMARY")
    if all_action_items:
        print(f"  {len(all_action_items)} action item(s) require attention:\n")
        for i, item in enumerate(all_action_items, 1):
            print(f"  {i}. {item}")
    else:
        print("  ✓ No action items — DB content matches application expectations")

    print()

    if args.output:
        sys.stdout = original_stdout  # type: ignore
        with open(args.output, "w") as f:
            f.write(buffer.getvalue())  # type: ignore
        print(f"Report saved to {args.output}")

    sys.exit(1 if all_action_items else 0)


if __name__ == "__main__":
    main()
