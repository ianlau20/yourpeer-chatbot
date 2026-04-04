# Testing Guide

## Overview

The test suite covers 381 tests across 14 unit/integration test files, plus an LLM-as-judge evaluation framework with 85 scenarios. Tests validate every backend module: slot extraction (regex and LLM-based), PII redaction, conversational routing, crisis detection, location boundary enforcement, query template correctness, confirmation flow, quick replies, audit logging, admin API routes, chat HTTP endpoint, Pydantic model validation, Claude client initialization, API configuration, and session management. All tests run without external services — the Streetlives database, Claude API is mocked where needed.

## Running Tests

From the repo root with the virtual environment activated:

```
source backend/venv/bin/activate
```

**Run all tests with pytest (recommended):**

```
pip install pytest httpx
pytest tests/ -v
```

**Run a single test file:**

```
pytest tests/test_chatbot.py -v
```

**Run a single test:**

```
pytest tests/test_chatbot.py::test_confirm_deny_breaks_loop -v
```

**Run LLM-as-judge evaluation (requires API key):**

```
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py
```

**Run LLM integration tests (requires API key):**

```
ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_llm_slot_extractor.py -v
```

Without `ANTHROPIC_API_KEY`, the 5 live LLM tests are automatically skipped.

## Test Coverage Map

All 14 backend modules and all 53 public functions are covered:

| Module | Test file(s) | Tests | Status |
|---|---|---|---|
| `chatbot.py` | `test_chatbot.py`, `test_edge_cases.py`, `test_chat_route.py` | 75+ | Full |
| `slot_extractor.py` | `test_slot_extractor.py`, `test_edge_cases.py`, `test_location_boundaries.py` | 101+ | Full |
| `query_templates.py` | `test_query_templates.py`, `test_location_boundaries.py` | 49+ | Full |
| `query_executor.py` | `test_location_boundaries.py`, `test_edge_cases.py` | 65 | Full |
| `audit_log.py` | `test_audit_log.py`, `test_admin.py` | 35+ | Full |
| `crisis_detector.py` | `test_crisis_detector.py` | 20 | Full |
| `llm_slot_extractor.py` | `test_llm_slot_extractor.py` | 19 | Full |
| `pii_redactor.py` | `test_pii_redactor.py`, `test_edge_cases.py` | 12+ | Full |
| `session_store.py` | `test_session_store.py`, `test_chatbot.py`, `test_chat_route.py` | 7+ | Full |
| `chat_models.py` | `test_chat_route.py` | 16 | Full |
| `admin.py` (routes) | `test_admin.py` | 18 | Full |
| `chat.py` (route) | `test_chat_route.py` | 14 | Full |
| `claude_client.py` | `test_claude_client.py` | 12 | Full |
| `main.py` | `test_main.py` | 7 | Full |

**Not covered:** Frontend TypeScript/React components (`frontend-next/`). There is no frontend test infrastructure in the project yet. See "Known Limitations" section below.

## Test Suites

### `test_chatbot.py` — 47 tests

Validates the main chatbot module — message classification, slot extraction routing, PII redaction integration, confirmation flow, quick replies, and LLM fallback. External dependencies are mocked.

| Category | Tests | What's covered |
|---|---|---|
| Message classification | 10 | All routing categories: reset, greeting, thanks, help, service, general, confirm_yes, confirm_deny, confirm_change_service, confirm_change_location, bot_identity, frustration, escalation. Long messages not misclassified as greetings. Punctuation handling |
| Routing paths | 9 | Greeting (with and without existing session), reset, thanks, help, service with results, no results, partial slots trigger follow-up, general conversation |
| Fallback behavior | 3 | DB failure → Claude fallback. Both fail → safe static message. Query error → Claude fallback |
| Multi-turn sessions | 2 | Slot accumulation across turns with confirmation. Reset then new search |
| PII in chatbot flow | 2 | Name/phone redacted in transcript but slots still extract |
| Session ID | 2 | Auto-generated when none provided. Preserved when provided |
| Response structure | 2 | All 8 required keys present. Relaxed search flag |
| Confirmation & quick replies | 10 | Confirmation triggered, change location/service, greeting/reset/follow-up quick replies, new input re-extracts, results show post-search buttons |
| Bug fix regressions | 7 | "No" breaks confirmation loop, deny phrases classified correctly, cancel variants trigger reset, expanded frustration phrases, thanks-with-continuation falls through, empty/whitespace message guard |

### `test_slot_extractor.py` — 37 tests

Validates the regex-based slot extraction pipeline.

| Category | Tests | What's covered |
|---|---|---|
| Service type | 10 | All 9 categories plus false positive prevention |
| Location | 6 | Preposition patterns, known NYC names, "near me" detection, false positives |
| Age | 3 | Multiple formats, out-of-range rejection |
| Urgency | 2 | High and medium levels |
| Multi-slot | 2 | Single message filling multiple slots |
| Merge logic | 5 | New over empty, preserving existing, near-me sentinel behavior |
| Flow control | 5 | `is_enough_to_answer`, follow-up question routing |

### `test_edge_cases.py` — 28 tests

Cross-cutting tests from the architecture spec and user testing plans.

| Category | Tests | What's covered |
|---|---|---|
| Location normalization | 4 | Borough → DB city mapping, neighborhood mapping, unknown locations, whitespace |
| Template resolution | 2 | All service types resolve. Unknown types return None |
| Multi-intent | 1 | "Food and shelter" picks first match (documented limitation) |
| Location edge cases | 4 | Non-NYC locations, mixed case, mid-conversation changes |
| Minor + urgency | 3 | 17-year-old shelter scenario from the architecture spec |
| PII + slot interaction | 3 | Name redacted but slots preserved. Age not treated as PII |
| Near-me multi-turn | 1 | Full simulation through to query |
| Empty / garbage input | 5 | Empty string, whitespace, single words, bare numbers |
| Keyword overlap | 5 | "Mental health" → mental_health, "food stamps" → other, etc. |

### `test_location_boundaries.py` — 65 tests

Validates location normalization, borough expansion, proximity search, and that queries stay within NYC boundaries.

| Category | Tests | What's covered |
|---|---|---|
| State filter | 3 | NY state filter present in all templates, preserved in relaxed queries |
| City filter | 2 | Exact match for strict, normalized borough names |
| Relaxed boundaries | 4 | City broadened to LIKE not dropped, eligibility/schedule dropped but location kept |
| Borough normalization | 3 | All 5 boroughs, all aliases, case-insensitive |
| Location extraction | 6 | Full sentences, non-NYC locations, "near me in Brooklyn" |
| Query builder | 6 | Filter presence based on params, defaults and overrides |
| Borough expansion | 7 | Queens/Brooklyn/Manhattan expand to neighborhoods, ANY() SQL |
| Neighborhood proximity | 15 | All neighborhoods have coordinates within NYC bounds, proximity search integration |
| DB connection | 1 | `test_connection` returns False without DATABASE_URL |

### `test_query_templates.py` — 49 tests

Validates query template correctness, SQL structure, service card formatting, and schedule computation.

| Category | Tests | What's covered |
|---|---|---|
| Taxonomy names | 10 | Every template's taxonomy_name validated against actual DB values |
| Base query structure | 5 | Required JOINs, phone priority, schedule LATERAL, location slug |
| Service card formatting | 10 | All fields, YourPeer URL, website fallback, URL normalization |
| Schedule status | 9 | None values, string/object times, midnight wrap, invalid inputs |
| Time formatting | 6 | Cross-platform (no %-I), all periods, no leading zeros |
| Deduplication | 5 | Removes by service_id, keeps first, edge cases |
| Generated SQL | 4 | Parameterized (no injection), strict vs relaxed params |

### `test_crisis_detector.py` — 20 tests

Validates crisis detection across five categories with correct hotline resources and no false positives.

| Category | Tests | What's covered |
|---|---|---|
| Suicide / self-harm | 4 | Direct statements, self-harm, 988 + Crisis Text Line + Trevor Project |
| Violence | 2 | Threats, 911 in response |
| Domestic violence | 3 | Abuse language, National DV + NYC DV hotlines |
| Trafficking | 2 | Labor/sex trafficking, National Trafficking Hotline |
| Medical emergency | 3 | Emergency language, 911, Poison Control |
| False positive prevention | 3 | Service requests, conversational messages, "hurt" in non-crisis context |
| Priority / integration | 3 | `is_crisis()` helper, crisis in longer messages, crisis alongside service requests |

### `test_llm_slot_extractor.py` — 14 unit + 5 live tests

Validates the LLM-based slot extractor. Live tests require `ANTHROPIC_API_KEY` and are automatically skipped without it.

| Category | Tests | What's covered |
|---|---|---|
| LLM extraction (mocked) | 6 | Service+location, age+gender+urgency, third-person, contradicting locations, empty messages, API failure |
| Smart extractor (tiered) | 5 | Regex sufficient → LLM skipped, regex partial → LLM called, ambiguous → LLM, merge logic, LLM failure falls back |
| Complexity routing | 3 | Short messages → simple, long messages → complex, unknown locations → complex |
| Integration (live) | 5 | End-to-end extraction, skipped without API key |

### `test_audit_log.py` — 35 tests

Validates all 13 public functions in the audit log module.

| Category | Tests | What's covered |
|---|---|---|
| Log conversation turn | 5 | Correct fields, internal slot stripping (`_pending_confirmation`, `transcript`, None values), quick reply label extraction, None slots, conversation registration |
| Log query execution | 1 | Dual insertion (events + query log), `max_results` stripped |
| Log crisis detected | 1 | Event fields, session association |
| Log session reset | 1 | Event logged |
| Get recent events | 3 | Limit, type filtering, returns latest not earliest |
| Get conversation | 2 | Multi-event-type sessions, empty for unknown IDs |
| Get conversations summary | 5 | Turn count aggregation, crisis flag, limit, recency sort, categories as lists (JSON-serializable) |
| Get query log | 2 | Only queries, limit |
| Get stats | 5 | All counters, category/service distributions, relaxed query rate, empty state |
| Eval results | 5 | Set/get round-trip, deep copy isolation, None when unset, file loading, missing file |
| Clear | 1 | Wipes everything including eval results |
| Ring buffer | 3 | Caps at MAX_EVENTS, evicts oldest, conversation index stays within MAX_CONVERSATIONS |
| Thread safety | 1 | 17 concurrent threads logging and reading simultaneously |

### `test_admin.py` — 18 tests

HTTP-level tests for the admin API endpoints using FastAPI TestClient.

| Category | Tests | What's covered |
|---|---|---|
| Stats | 2 | Empty state returns zeros, populated state returns correct counts |
| Conversations list | 3 | Summaries, limit parameter, limit validation (rejects 0 and 999) |
| Conversation detail | 3 | All event types returned, 404 for unknown ID, crisis session includes both event types |
| Events | 5 | All events, type filtering, invalid type → 422, limit, limit validation |
| Queries | 2 | Returns only query executions, limit |
| Eval | 2 | 200 with null results when empty, returns data when set |
| Health | 1 | `GET /api/health` returns ok |

### `test_chat_route.py` — 30 tests

HTTP-level tests for the chat endpoint and Pydantic model validation.

| Category | Tests | What's covered |
|---|---|---|
| ChatRequest model | 5 | Valid construction, optional session_id, missing message rejected, wrong type, empty string |
| ServiceCard model | 4 | Minimal (service_name only), full (all 13 fields), missing required rejected, serialization |
| QuickReply model | 3 | Valid, missing label rejected, missing value rejected |
| ChatResponse model | 4 | Minimal with defaults, nested ServiceCards, missing required rejected, JSON round-trip |
| HTTP basics | 8 | Valid 200, session_id generated/preserved, missing message 422, non-JSON 422, no body 422, empty message guard, response schema validation |
| HTTP multi-turn | 4 | Full conversation with service cards, slot accumulation, reset, quick reply structure |
| HTTP crisis | 1 | Returns 988 resources, no service cards, query_services not called |
| HTTP method | 1 | GET /chat/ returns non-200 |

### `test_pii_redactor.py` — 12 tests

Validates PII detection and redaction across six PII types.

| Category | Tests | What's covered |
|---|---|---|
| Phone numbers | 1 | 5 formats |
| SSN | 1 | Hyphenated and space-separated |
| Email | 1 | Standard format |
| Dates of birth | 1 | 4 formats |
| Street addresses | 2 | Named streets (123 Main Street), numbered streets (456 West 42nd Street, 789 5th Avenue), Broadway. False positive prevention (bare street names without house numbers) |
| Names | 1 | Intro phrases with blocklist |
| False positives | 2 | NYC locations and service keywords not redacted |
| Multiple PII | 1 | Combined detection |
| Clean passthrough | 1 | No PII → no changes |
| Quick check | 1 | `has_pii()` utility |

### `test_claude_client.py` — 12 tests

Unit tests for the Claude LLM client. All external calls mocked.

| Category | Tests | What's covered |
|---|---|---|
| Lazy initialization | 2 | First call creates client, subsequent calls reuse it |
| Missing env vars | 1 | Missing `ANTHROPIC_API_KEY` raises |
| Error caching | 2 | Init failure cached (no retry), `genai.Client()` failure cached |
| Reply success | 2 | Returns response text, None text → empty string |
| Reply failure | 2 | API exception → fallback string, init failure → fallback string |

### `test_session_store.py` — 7 tests

Validates session CRUD and thread safety.

| Category | Tests | What's covered |
|---|---|---|
| Basic operations | 5 | Save/get round-trip with deep copy, nonexistent returns {}, clear, clear nonexistent, overwrite |
| Thread safety | 2 | 30 concurrent threads (1,500 operations), lock existence |

### `test_main.py` — 7 tests

HTTP-level tests for the FastAPI app configuration (headless API mode).

| Category | Tests | What's covered |
|---|---|---|
| Health | 1 | `GET /api/health` |
| Root | 1 | `GET /` returns JSON message (no static file serving) |
| API routing | 3 | `/api/health`, `POST /chat/`, `/admin/api/stats` all routed correctly |
| CORS | 2 | Headers present, preflight OPTIONS |

## LLM-as-Judge Evaluation (`eval_llm_judge.py`)

Beyond unit tests, the system includes an end-to-end evaluation framework that uses Claude as an impartial judge to score full conversations. This validates the chatbot holistically — not just whether individual functions return the right values, but whether the overall experience is safe, efficient, and appropriate for the population served.

### How it works

The evaluation runs a three-stage pipeline:

**Stage 1 — Conversation Simulator.** Each scenario defines a persona, an opening message, and expected behavior. The simulator drives multi-turn conversations through `generate_reply()` with mocked DB results. Pre-defined user messages are sent first. If the bot asks follow-up questions, Claude (Sonnet) generates natural user responses consistent with the scenario persona.

**Stage 2 — LLM Judge.** The completed transcript and scenario metadata are sent to a separate Claude call with a detailed scoring rubric. The judge scores 8 quality dimensions on a 1–5 scale with written justifications.

**Stage 3 — Report Generator.** Individual evaluations are aggregated into a structured report with overall average, per-dimension breakdowns, per-category averages, critical failure list, and per-scenario detail.

### Scoring dimensions

| Dimension | What it measures |
|---|---|
| Slot Extraction Accuracy | Did the system correctly identify service type, location, age, and urgency? |
| Dialog Efficiency | How many turns to reach a result? Were follow-ups necessary and well-targeted? |
| Response Tone | Warm, respectful, non-judgmental, trauma-informed? |
| Safety & Crisis Handling | Did crisis language trigger appropriate resources? |
| Confirmation UX | Was the confirmation step clear? Could the user change details? |
| Privacy Protection | Was PII avoided in responses? No echoing of names, phones, or addresses? |
| Hallucination Resistance | Did the system avoid fabricating service data? |
| Error Recovery | When things went wrong, did the system recover gracefully? |

### Running the evaluation

```bash
# Run all 85 scenarios
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py

# Run only crisis scenarios
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py --category crisis

# Run a single scenario and save JSON report
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py --scenario-id shelter_queens_17 --output eval_report.json
```

## Known Limitations

These are documented behaviors, not bugs:

- **Bare numbers (regex only):** Replying with just "17" (no context like "I am" or "age") does not extract age with the regex extractor. LLM extraction handles this correctly when enabled.
- **Multi-intent:** "I need food and shelter" extracts only the first matching service type. One service per query.
- **Name detection:** Heuristic-based (intro phrases like "my name is"). Won't catch names without an intro phrase. Acceptable tradeoff to avoid false positives on location names.
- **Borough typos (regex only):** Misspellings like "brookyln" are not corrected by regex. LLM extraction handles these.
- **Two boroughs in one message (regex only):** "I'm in Queens but looking for food in Brooklyn" extracts "Queens" (first preposition match), not Brooklyn. LLM extraction picks the intended location.
- **Manhattan / "New York" ambiguity:** Manhattan normalizes to DB city value "New York." PostGIS proximity search mitigates this for neighborhood-level queries.
- **Audit log is in-memory:** Staff review console data is lost on server restart. For production, replace with a persistent store.
- **Frontend untested:** No frontend test infrastructure exists yet. The Next.js components in `frontend-next/` (chat UI, admin console, hooks, Zustand store) have no automated tests. Consider adding Playwright for E2E tests or Vitest for component tests when stabilizing for production.

## Adding New Tests

Follow the existing pattern. For chatbot tests that need external services mocked:

```python
@patch("app.services.chatbot.query_services", return_value=MOCK_QUERY_RESULTS)
@patch("app.services.chatbot.claude_reply")
def test_your_new_test(mock_claude, mock_query):
    clear_session("test-new")
    result = generate_reply("your test message", session_id="test-new")
    assert result["response"] == "expected"
    clear_session("test-new")
```

For HTTP-level tests using TestClient:

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_your_endpoint():
    response = client.post("/chat/", json={"message": "hello"})
    assert response.status_code == 200
```

For tests that modify shared state (audit log, session store), always call the appropriate `clear` function at the start:

```python
from app.services.audit_log import clear_audit_log

def test_your_audit_test():
    clear_audit_log()
    # ... test logic ...
```
