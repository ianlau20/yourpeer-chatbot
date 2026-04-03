# Testing Guide

## Overview

The test suite covers 180 tests across six files, validating the slot extraction pipeline, PII redaction, conversational routing, location boundary enforcement, query template correctness, and cross-cutting edge cases. All tests run without external services — the Streetlives database and Gemini LLM are mocked where needed.

## Running Tests

From the repo root with the virtual environment activated:

```
source backend/venv/bin/activate
```

**Run all tests:**

```
cd tests
python test_pii_redactor.py && python test_slot_extractor.py && python test_edge_cases.py && python test_chatbot.py && python test_location_boundaries.py && python test_query_templates.py
```

**Run a single suite:**

```
python tests/test_slot_extractor.py
```

**Run with pytest (if installed):**

```
pip install pytest
pytest tests/ -v
```

## Test Suites

### `test_pii_redactor.py` — 11 tests

Validates the PII detection and redaction pipeline that scrubs personally identifiable information from user messages before they are stored.

| Category | Tests | What's covered |
|---|---|---|
| Phone numbers | 5 | Formats: (212) 555-1234, 212-555-1234, 212.555.1234, 2125551234, +1 212 555 1234 |
| SSN | 1 | Pattern: 123-45-6789, 123 45 6789 |
| Email | 1 | Pattern: user@domain.com |
| Dates of birth | 1 | Formats: 01/15/1990, 1-15-90, January 15, 1990, Jan 15 1990 |
| Street addresses | 1 | Patterns: 123 Main Street, 456 Broadway, 789 Flatbush Ave |
| Names | 1 | Intro phrases: "My name is John Smith", "Call me David", "I'm Sarah" |
| False positive prevention | 2 | NYC locations (Brooklyn, Queens, Harlem) and service keywords (food, shelter, homeless) are NOT redacted |
| Multiple PII | 1 | Message with name + phone + email all redacted correctly |
| Clean passthrough | 1 | Messages without PII pass through unchanged |
| Quick check | 1 | `has_pii()` utility function |

### `test_slot_extractor.py` — 36 tests

Validates the slot-filling engine that extracts service type, location, age, and urgency from user messages.

| Category | Tests | What's covered |
|---|---|---|
| Service type extraction | 10 | All 9 categories (food, shelter, clothing, personal care, medical, mental health, legal, employment, other) plus false positive prevention |
| Location extraction | 6 | "in X" pattern, preposition variants (near/around/by/from), known NYC names, "near me" detection, false positive prevention ("in need", "in trouble"), clean messages |
| Age extraction | 3 | Formats: "I am 17", "I'm 22", "age 30", "65 years old". Out-of-range rejection (0, 150) |
| Urgency extraction | 2 | High (tonight, urgent, asap) and medium (soon, this week) |
| Multi-slot extraction | 2 | Single message filling multiple slots. Full sentence parsing |
| Merge logic | 5 | New over empty, preserving existing, overriding with new, near-me sentinel behavior (doesn't override real location, real location replaces sentinel) |
| Flow control | 5 | `is_enough_to_answer` with various slot combinations including near-me sentinel. Follow-up question routing (service type first, location second, age for shelter) |

### `test_edge_cases.py` — 28 tests

Cross-cutting tests that validate interactions between modules and cover scenarios from the architecture spec and user testing plans.

| Category | Tests | What's covered |
|---|---|---|
| Location normalization | 4 | Borough → DB city mapping (Manhattan → New York), neighborhood mapping (Harlem → New York), unknown locations pass through, whitespace stripping |
| Template resolution | 2 | All service types resolve to a query template. Unknown types return None |
| Multi-intent | 1 | "I need food and shelter" picks the first match (documented limitation) |
| Location edge cases | 4 | Non-NYC location still extracted, mixed case, location change mid-conversation, service type change mid-conversation |
| Minor + urgency | 3 | 17-year-old needing shelter tonight (from the architecture spec scenario). Shelter triggers age follow-up, food does not |
| PII + slot interaction | 3 | Name redacted but food + location still extracted. Age (17) not treated as PII. Phone redacted but location preserved |
| Near-me multi-turn | 1 | Full simulation: "food near me" → follow-up → "Brooklyn" → query fires |
| Empty / garbage input | 5 | Empty string, whitespace-only, single-word borough, single-word service, bare number |
| Keyword overlap | 5 | "mental health" → mental_health (not medical), "health care" → medical, "food stamps" → other (not food), "legal aid" → legal, "job training" → employment |

### `test_chatbot.py` — 28 tests

Validates the main chatbot module — the central routing logic that ties together message classification, slot extraction, PII redaction, database queries, and LLM fallback. External dependencies are mocked with `unittest.mock.patch`.

| Category | Tests | What's covered |
|---|---|---|
| Message classification | 9 | All 6 categories (reset, greeting, thanks, help, service, general). Long messages not misclassified as greetings. Reset takes priority. Punctuation handling |
| Routing paths | 9 | Greeting (with and without existing session), reset (confirms session cleared), thanks, help, service with DB results, service with no results, partial slots trigger follow-up, general conversation routes to Gemini |
| Fallback behavior | 3 | DB failure → Gemini fallback. Both DB + Gemini failure → safe static message. Query error key → Gemini fallback |
| Multi-turn sessions | 2 | Slot accumulation across turns (food + Brooklyn = query). Reset then new search starts clean |
| PII in chatbot flow | 2 | Name redacted in stored transcript but slots still extract. Phone redacted in transcript |
| Session ID | 2 | Auto-generated when none provided. Preserved when provided |
| Response structure | 2 | All 7 required keys present in every response. Relaxed search flag correctly set |

### `test_location_boundaries.py` — 30 tests

Validates that queries stay within NYC boundaries, location normalization maps correctly, the state filter is never dropped, and the relaxed fallback doesn't leak out-of-area results. Tests inspect generated SQL and parameters without requiring a database connection.

| Category | Tests | What's covered |
|---|---|---|
| State filter | 3 | NY state filter present in all templates, preserved in all relaxed queries, present even without a city param |
| City filter (strict) | 2 | Exact match used for strict queries. Normalized borough names flow through to params |
| Relaxed query boundaries | 4 | City broadened to LIKE (not dropped), city constraint always kept, eligibility dropped but location kept, schedule dropped but location kept |
| Borough normalization | 3 | All 5 boroughs normalize correctly, all aliases map to valid NYC cities, case-insensitive matching |
| Location extraction edge cases | 6 | Boroughs and neighborhoods in full sentences, non-NYC locations don't normalize to NYC boroughs, "near me in Brooklyn" extracts Brooklyn, two-borough messages (documented), typos (documented) |
| Query builder filters | 6 | City filter present/absent based on params, age triggering eligibility, hidden filter always present, taxonomy filter always present, max_results default and override |
| Relaxed query parameters | 2 | Strict vs relaxed param side-by-side comparison. Relaxed without city still has state filter |

### `test_query_templates.py` — 47 tests

Validates query template correctness — taxonomy names against the real DB, SQL structure, service card formatting, schedule computation, time formatting, deduplication, and generated SQL safety.

| Category | Tests | What's covered |
|---|---|---|
| Taxonomy names | 8 | Every template's taxonomy_name validated against actual DB values. Explicit checks for Healthcare → Health and Legal → Legal Services fixes. All 7 templates verified |
| Base query structure | 5 | All required JOINs present. Phone uses LATERAL with LIMIT 1 and location > service > org priority. Schedule uses LATERAL with ISODOW. Location slug selected |
| Service card formatting | 9 | All fields populated, YourPeer URL from slug (present and absent), missing optional fields, website fallback (service → org URL), empty/partial address, None service_name defaults to "Unknown Service" |
| Schedule status | 9 | None values, partial None, string times, time objects, midnight wrap (8 PM – 6 AM), invalid strings, mixed types, schedule flowing through to cards, no-data cards |
| Time formatting | 6 | Morning, afternoon, noon, midnight, 12:30 AM, no leading zeros (cross-platform fix) |
| Deduplication | 5 | Removes duplicates by service_id, keeps first occurrence, empty list, rows without service_id skipped, all-unique passthrough |
| Generated SQL | 4 | All SQL uses :param placeholders (no raw values), strict has city not city_pattern, relaxed swaps to city_pattern, unknown template raises ValueError |

## Known Limitations

These are documented behaviors, not bugs:

- **Bare numbers:** Replying with just "17" (no context like "I am" or "age") does not extract age. The regex patterns require an intro phrase. LLM-based extraction would handle this.
- **Multi-intent:** "I need food and shelter" extracts only the first matching service type. The system handles one service per query.
- **Substring keyword matches:** The `other` category keyword `"id"` can false-match on words like "cold" or "did." Should be changed to a phrase like `"need an id"`.
- **Name detection:** Heuristic-based (intro phrases like "my name is"). Won't catch names mentioned without an intro phrase. Acceptable tradeoff to avoid false positives on location names.
- **Borough typos:** Misspellings like "brookyln" or "quens" are not corrected by the regex extractor. LLM-based extraction would handle this.
- **Two boroughs in one message:** "I'm in Queens but looking for food in Brooklyn" extracts the first preposition match ("Queens"), not the intended one. A known limitation of regex-based extraction.
- **Manhattan / "New York" ambiguity:** Manhattan normalizes to the DB city value "New York," which could theoretically match non-Manhattan locations that also use "New York" as their city. The state filter (NY) prevents out-of-state results, but within-state ambiguity remains. Proper fix would use PostGIS proximity or the `nyc_neighborhoods` table.

## Adding New Tests

Follow the existing pattern: each test function is self-contained with setup, assertion, and cleanup. For tests that touch session state, always call `clear_session(sid)` at the end. For tests that depend on external services, use `@patch` decorators to mock `query_services` and `gemini_reply`.

```python
@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.gemini_reply")
def test_your_new_test(mock_gemini, mock_query):
    clear_session("test-new")
    result = generate_reply("your test message", session_id="test-new")
    assert result["response"] == "expected"
    clear_session("test-new")
```
