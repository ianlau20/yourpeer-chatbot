# Testing Guide

## Overview

The test suite covers 1344 tests across 27 test files, plus an LLM-as-judge evaluation framework with 142 scenarios. Tests validate every backend module: slot extraction (regex and LLM-based), PII redaction, conversational routing, crisis detection, crisis step-down, emotional handling (AVR pattern), frustration routing, phrase list audit coverage (C-SSRS, Joiner IPT, DV control, shame/stigma, grief, NYC service terms), contraction normalization, location boundary enforcement, query template correctness, confirmation flow, quick replies, audit logging, admin API routes, chat HTTP endpoint, Pydantic model validation, Claude client initialization, API configuration, session management, geolocation, rate limiting, request correlation IDs, privacy question handling, family composition, multi-service extraction, split classifier (action + tone), shelter taxonomy enrichment, word-boundary keyword collision prevention, and database schema/query integration. Unit tests run without external services (database and Claude API are mocked). Integration tests require DATABASE_URL and are automatically skipped without it.

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

All 17 backend modules and all public functions are covered:

| Module | Test file(s) | Tests | Status |
|---|---|---|---|
| `chatbot.py` | `test_chatbot.py`, `test_edge_cases.py`, `test_chat_route.py` | 168+ | Full |
| `slot_extractor.py` | `test_slot_extractor.py`, `test_edge_cases.py`, `test_location_boundaries.py` | 147+ | Full |
| `rag/__init__.py` | `test_query_templates.py`, `test_geolocation.py`, `test_db_integration.py` | 90+ | Full |
| `query_templates.py` | `test_query_templates.py`, `test_location_boundaries.py` | 49+ | Full |
| `query_executor.py` | `test_location_boundaries.py`, `test_edge_cases.py` | 65 | Full |
| `audit_log.py` | `test_audit_log.py`, `test_admin.py` | 58+ | Full |
| `crisis_detector.py` | `test_crisis_detector.py` | 20 | Full |
| `llm_slot_extractor.py` | `test_llm_slot_extractor.py` | 19 | Full |
| `pii_redactor.py` | `test_pii_redactor.py`, `test_edge_cases.py` | 12+ | Full |
| `session_store.py` | `test_session_store.py`, `test_chatbot.py`, `test_chat_route.py` | 7+ | Full |
| `session_token.py` | `test_session_token.py`, `test_chat_route.py` | 17 | Full |
| `rate_limiter.py` | `test_rate_limiter.py`, `test_rate_limit_integration.py` | 24 | Full |
| `chat_models.py` | `test_chat_route.py` | 27 | Full |
| `admin.py` (routes) | `test_admin.py` | 27 | Full |
| `chat.py` (route) | `test_chat_route.py` | 24 | Full |
| `claude_client.py` | `test_claude_client.py` | 19 | Full |
| `bot_knowledge.py` | `test_bot_knowledge.py` | 62 | Full |
| `main.py` | `test_main.py` | 14 | Full |

**Not covered:** Frontend TypeScript/React components (`frontend-next/`). There is no frontend test infrastructure in the project yet. See "Known Limitations" section below.

## Test Suites

### `test_chatbot.py` — 140 tests

Validates the main chatbot module — message classification (split classifier), slot extraction routing, PII redaction integration, confirmation flow, quick replies, emotional awareness, bot questions, privacy question handling, static fallbacks, context-aware yes/no, frustration loop detection, family composition, combined action+tone routing, tone prefix assertions, escalation guard, and LLM fallback. External dependencies are mocked.

| Category | Tests | What's covered |
|---|---|---|
| `_classify_action` | 13 | Reset, greeting (short/long), confirm_yes, confirm_deny, bot_question, escalation, help, returns None for service, returns None for emotional, returns None for frustrated, returns None for confused, returns None for urgent |
| `_classify_tone` | 10 | Emotional, frustrated, confused, None for neutral, no service-word gate (detects emotion even with "need"/"food" present), urgent phrases (7 variants), emotional beats urgent, pure urgency |
| Combined routing | 10 | Emotional+service → service with prefix, help+service → service, escalation+service → service, confused+service → service with prefix, frustrated+service → service with prefix, pure emotional/help/escalation still work, urgent+service gets prefix |
| Escalation guard | 3 | Escalation+service without location → escalation, escalation+service+location → service, "talk to someone about shelter" → escalation |
| Message classification | 13 | All 16 routing categories including emotional, bot_question. Long messages not misclassified as greetings. Punctuation handling. Emotional distinct from confused. Bot question distinct from frustration and help |
| Privacy classification | 2 | 19 privacy phrases (ICE, police, benefits, recording, anonymity) all route to bot_question. Privacy phrasing not misclassified as service request |
| Routing paths | 12 | Greeting (with and without existing session), reset, thanks, help, bot question (direct answer, no slot extraction), service with results, no results, partial slots trigger follow-up, general conversation |
| Emotional awareness | 6 | Emotional classification (12 phrases), false negatives (service messages not caught), distinct from confused, peer navigator offered, no confirmation set, static fallback without LLM |
| Context-aware yes/no | 12 | "Yes"/"no" after escalation, emotional, frustration, confused — each with appropriate response. "Yes" after frustration resets. "Yes" after confused escalates. "No" after emotional has quick replies. Context cleared after unrelated message |
| Pending confirmation | 2 | Escalation clears pending confirmation, crisis clears pending confirmation |
| No pushy buttons | 2 | General responses don't push service menu after first turn, no menu mid-search |
| Frustration loop | 3 | Repeated frustration produces different response, pushes navigator harder, shorter than first response |
| Static bot answers | 14 | Pattern-matched fallbacks for: geolocation failure, geolocation general, outside NYC (211), service categories, ICE privacy, police privacy, benefits privacy, who-can-see, delete/clear, identity/anonymity, general privacy, how-it-works, unknown default |
| Bot question full flow | 3 | Privacy question gets specific answer, geolocation question explains failure, outside-NYC mentions coverage |
| Fallback behavior | 3 | DB failure → Claude fallback. Both fail → safe static message. Query error → Claude fallback |
| Multi-turn sessions | 2 | Slot accumulation across turns with confirmation. Reset then new search |
| Geolocation priority | 1 | Text location overrides stored browser coordinates from prior near-me search |
| PII in chatbot flow | 4 | Name/phone redacted in transcript but slots still extract, bot response PII (name) redacted before audit log, bot response PII (phone) redacted before audit log |
| Session ID | 2 | Auto-generated when none provided. Preserved when provided |
| Response structure | 2 | All 8 required keys present. Relaxed search flag |
| Service detail in confirmation | 3 | Confirmation uses service_detail ("dental care" not "health care"), falls back to generic label, change-service clears detail |
| Family status in confirmation | 6 | Confirmation mentions "children", "family", "yourself" per status. No mention when not set. Family status extracted during multi-turn shelter flow. family_status reaches query_services via _execute_and_respond |
| Confirmation & quick replies | 10 | Confirmation triggered, change location/service, greeting/reset/follow-up quick replies, new input re-extracts, results show post-search buttons |
| Bug fix regressions | 7 | "No" breaks confirmation loop, deny phrases classified correctly, cancel variants trigger reset, expanded frustration phrases, thanks-with-continuation falls through, empty/whitespace message guard |

### `test_slot_extractor.py` — 102 tests

Validates the regex-based slot extraction pipeline.

| Category | Tests | What's covered |
|---|---|---|
| Service type | 10 | All 9 categories plus false positive prevention |
| "Other services" keyword | 2 | Quick reply value "I need other services" and singular form both extract service_type=other |
| Service detail extraction | 7 | Sub-type labels: dental→dental care, therapy→therapy, immigration→immigration services, shower→showers, food pantry→food pantries, AA meeting→AA meetings. Generic "food" has no detail |
| Multi-service extraction | 17 | Two services, three services, no duplicate categories, "mental health" doesn't double-match "health", sub-type details preserved per service, single/no service edge cases, extract_slots returns primary + additional_services, merge_slots skips additional_services, complex multi-intent, find() scans forward past overlaps, text-position ordering (forward and reversed), word-boundary position ordering |
| Location | 6 | Preposition patterns, known NYC names, "near me" detection, false positives |
| Age | 3 | Multiple formats, out-of-range rejection |
| Urgency | 2 | High and medium levels |
| Family status extraction | 5 | Children phrases (7 variants), single parent→with_children, partner/spouse→with_family, alone phrases (5 variants), no false positives on non-family messages |
| Family status false positives | 3 | "I have a question" not matched, "me and my friend" not matched, "feeling alone" (emotional) not matched |
| Family status combined | 1 | Children + service_type + location extracted together |
| Family follow-up | 3 | Shelter asks about family when age provided, food doesn't ask, already-set family not re-asked |
| Multi-slot | 2 | Single message filling multiple slots |
| Merge logic | 11 | New over empty, preserving existing, near-me sentinel behavior, stale service_detail cleared on service change, detail persists when service unchanged, new detail replaces old, additional_services skipped during merge |
| Flow control | 5 | `is_enough_to_answer`, follow-up question routing |
| Word-boundary keywords | 12 | Restored collision-prone keywords (bed, wash, id, eat, hat) match correctly and don't false-positive on location names |
| New keywords | 10 | Expanded coverage across all 9 categories + urgency terms for target population |

### `test_edge_cases.py` — 29 tests

Cross-cutting tests from the architecture spec and user testing plans.

| Category | Tests | What's covered |
|---|---|---|
| Location normalization | 4 | Borough → DB city mapping, neighborhood mapping, unknown locations, whitespace |
| Template resolution | 2 | All service types resolve. Unknown types return None |
| Multi-intent | 1 | "Food and shelter" extracts both; first is searched, second queued (PR 3) |
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

### `test_query_templates.py` — 90 tests

Validates query template correctness, SQL structure, service card formatting, schedule computation, result sorting, and shelter taxonomy enrichment.

| Category | Tests | What's covered |
|---|---|---|
| Taxonomy names | 10 | Every template's taxonomy_name validated against actual DB values |
| Base query structure | 5 | Required JOINs, phone priority, schedule LATERAL, location slug |
| Service card formatting | 10 | All fields, YourPeer URL, website fallback, URL normalization |
| Schedule status | 9 | None values, string/object times, midnight wrap, invalid inputs |
| Time formatting | 6 | Cross-platform (no %-I), all periods, no leading zeros |
| Deduplication | 5 | Removes by service_id, keeps first, edge cases |
| Generated SQL | 4 | Parameterized (no injection), strict vs relaxed params |
| Result sorting | 6 | Open-now priority, proximity-first with distance, freshness ordering, relaxed sort consistency |
| Shelter taxonomy enrichment | 8 | Youth (age<18), senior (age≥62), families (with_children), single adult (alone), LGBTQ Young Adult (always), base taxonomies preserved, food queries not enriched, TEMPLATES default_params not mutated |

### `test_crisis_detector.py` — 36 tests

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

### `test_llm_slot_extractor.py` — 19 unit + 5 live tests

Validates the LLM-based slot extractor. Live tests require `ANTHROPIC_API_KEY` and are automatically skipped without it.

| Category | Tests | What's covered |
|---|---|---|
| LLM extraction (mocked) | 6 | Service+location, age+gender+urgency, third-person, contradicting locations, empty messages, API failure |
| Smart extractor (tiered) | 5 | Regex sufficient → LLM skipped, regex partial → LLM called, ambiguous → LLM, merge logic, LLM failure falls back |
| Complexity routing | 3 | Short messages → simple, long messages → complex, unknown locations → complex |
| Integration (live) | 5 | End-to-end extraction, skipped without API key |

### `test_audit_log.py` — 58 tests

Validates all 13 public functions in the audit log module.

| Category | Tests | What's covered |
|---|---|---|
| Log conversation turn | 5 | Correct fields, internal slot stripping (`_pending_confirmation`, `transcript`, None values), quick reply label extraction, None slots, conversation registration |
| Request correlation IDs | 4 | request_id stored in turn events, defaults to None, stored in query execution, stored in crisis events |
| Log query execution | 1 | Dual insertion (events + query log), `max_results` stripped |
| Log crisis detected | 1 | Event fields, session association |
| Log session reset | 1 | Event logged |
| Get recent events | 3 | Limit, type filtering, returns latest not earliest |
| Get conversation | 2 | Multi-event-type sessions, empty for unknown IDs |
| Get conversations summary | 5 | Turn count aggregation, crisis flag, limit, recency sort, categories as lists (JSON-serializable) |
| Get query log | 2 | Only queries, limit |
| Get stats (basic) | 5 | All counters, category/service distributions, relaxed query rate, empty state |
| Get stats (pilot metrics) | 10 | Escalation count, service intent sessions, slot correction rate, confirmation breakdown, confirmation abandon rate, slot confirmation rate (partial + full), data freshness rate, no-query edge case, legacy queries without freshness |
| Get stats (conversation quality) | 7 | Emotional detection rate, emotional → escalation, emotional → service, bot question rate, bot question → frustration, conversational discovery rate, empty state |
| Eval results | 5 | Set/get round-trip, deep copy isolation, None when unset, file loading, missing file |
| Clear | 1 | Wipes everything including eval results |
| Ring buffer | 3 | Caps at MAX_EVENTS, evicts oldest, conversation index stays within MAX_CONVERSATIONS |
| Thread safety | 1 | 17 concurrent threads logging and reading simultaneously |

### `test_admin.py` — 27 tests

HTTP-level tests for the admin API endpoints using FastAPI TestClient.

| Category | Tests | What's covered |
|---|---|---|
| Admin auth | 5 | Open when no key set, rejects missing header, rejects wrong key, accepts correct key, protects eval/run |
| Stats | 2 | Empty state returns zeros, populated state returns correct counts |
| Conversations list | 3 | Summaries, limit parameter, limit validation (rejects 0 and 999) |
| Conversation detail | 3 | All event types returned, 404 for unknown ID, crisis session includes both event types |
| Events | 5 | All events, type filtering, invalid type → 422, limit, limit validation |
| Queries | 2 | Returns only query executions, limit |
| Eval | 2 | 200 with null results when empty, returns data when set |
| Eval run guards | 2 | 500 when no API key, 409 when already running |
| Admin rate limits | 2 | 429 after exceeding IP limit, stricter eval/run limit |
| Health | 1 | `GET /api/health` returns ok |

### `test_chat_route.py` — 46 tests

HTTP-level tests for the chat endpoint and Pydantic model validation.

| Category | Tests | What's covered |
|---|---|---|
| ChatRequest model | 8 | Valid construction, optional session_id, missing message rejected, wrong type, empty string, accepts 1,000-char message, rejects 1,001-char message, rejects oversized at HTTP level (422) |
| Coordinate validation | 5 | Valid coordinates accepted, boundary values (±90/±180), invalid latitude rejected, invalid longitude rejected, invalid coordinates return 422 |
| Request correlation ID | 2 | X-Request-ID echoed in response, generated when not provided |
| ServiceCard model | 4 | Minimal (service_name only), full (all 13 fields), missing required rejected, serialization |
| QuickReply model | 3 | Valid, missing label rejected, missing value rejected |
| ChatResponse model | 4 | Minimal with defaults, nested ServiceCards, missing required rejected, JSON round-trip |
| HTTP basics | 8 | Valid 200, session_id generated/preserved, missing message 422, non-JSON 422, no body 422, empty message guard, response schema validation |
| HTTP multi-turn | 4 | Full conversation with service cards, slot accumulation, reset, quick reply structure |
| HTTP crisis | 1 | Returns 988 resources, no service cards, query_services not called |
| HTTP method | 1 | GET /chat/ returns non-200 |
| Session token validation | 5 | Forged session_id → 403, tampered signature → 403, valid signed token → 200, first message mints signed token, feedback rejects forged token |

### `test_pii_redactor.py` — 15 tests

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

### `test_claude_client.py` — 19 tests

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

### `test_session_token.py` — 12 tests

Validates HMAC-signed session token generation and verification.

| Category | Tests | What's covered |
|---|---|---|
| No secret (dev mode) | 2 | Unsigned tokens generated, any string accepted |
| With secret (production) | 5 | Signed tokens generated, generate-then-validate round-trip, unsigned rejected, forged signature rejected, tampered payload rejected |
| Edge cases | 3 | Empty string rejected, bare dot rejected, wrong secret rejected |
| Format robustness | 2 | Tokens with dots in raw portion handled correctly, constant-time comparison used |

### `test_geolocation.py` — 11 tests

Validates browser geolocation support: coordinate acceptance, session storage, "near me" + coords flow, and proximity query integration.

| Category | Tests | What's covered |
|---|---|---|
| Pydantic model | 2 | ChatRequest accepts lat/lng, coordinates optional |
| Session storage | 2 | Coords stored when provided, absent when not |
| Near-me + coords | 3 | Triggers confirmation (not borough ask), shows "near your location", sentinel not exposed |
| Full flow | 1 | food near me → confirmation → confirm → results with coords passed to query_services |
| RAG integration | 2 | Direct coords build proximity params, coords override location name |
| Cross-turn persistence | 1 | Coords persist in session across messages |

### `test_rate_limiter.py` — 14 tests

Validates the sliding-window rate limiter logic.

| Category | Tests | What's covered |
|---|---|---|
| Per-session limits | 4 | Messages per minute/hour/day, retry_after calculation |
| Per-IP limits | 3 | IP-level rate limiting, separate from session limits |
| Feedback limits | 2 | Feedback endpoint rate limiting |
| Bucket management | 3 | Sliding window cleanup, thread safety, clear() |
| Memory management | 2 | Forced eviction when bucket cap exceeded, no forced eviction under cap |

### `test_rate_limit_integration.py` — 10 tests

HTTP-level tests for rate limiting middleware via FastAPI TestClient.

| Category | Tests | What's covered |
|---|---|---|
| 429 responses | 4 | Rate limit exceeded returns 429, crisis resources included |
| Session tracking | 3 | Session-based vs IP-based limiting |
| Middleware integration | 3 | Middleware attached to routes, header extraction |

### `test_db_integration.py` — 53 tests

Database integration tests that run against the real Streetlives PostgreSQL database. Automatically skipped when DATABASE_URL is not set.

| Category | Tests | What's covered |
|---|---|---|
| Schema validation | 18 | All 11 tables exist, required columns present, PostGIS geometry type, JSONB eligibility, timestamp freshness column, taxonomy names match templates, eligibility parameters exist |
| Query execution | 21 | All 9 templates strict/relaxed, proximity search, distance ordering, age/gender eligibility, open-now sort, freshness sort, city list ANY(), weekday/open-now filters, all filters combined |
| Result formatting | 2 | Real rows format to valid service cards, proximity returns multiple results |
| End-to-end | 5 | Full query_services() pipeline: borough, neighborhood, coords, relaxed fallback, card field completeness |

### `test_main.py` — 14 tests

HTTP-level tests for the FastAPI app configuration (headless API mode).

| Category | Tests | What's covered |
|---|---|---|
| Health | 1 | `GET /api/health` |
| Root | 1 | `GET /` returns JSON message (no static file serving) |
| API routing | 3 | `/api/health`, `POST /chat/`, `/admin/api/stats` all routed correctly |
| CSRF protection | 6 | Valid origin allowed, evil origin → 403, non-browser (no headers) allowed, Sec-Fetch-Site without origin → 403, valid Referer allowed, evil Referer → 403 |
| CORS | 3 | Headers present for allowed origin, no headers for unknown origin, preflight OPTIONS |

### `test_structural_fixes.py` — 50 tests

Multi-turn conversation flow tests for structural fixes (R1-R8).

| Category | Tests | What's covered |
|---|---|---|
| Change mind | 10 | Service change during pending confirmation, implicit denial |
| Yes-after-escalation | 6 | Distinct response vs escalation repeat |
| Frustration loop | 8 | Counter increment, shorter second response, navigator push |
| Context-aware yes/no | 15 | Emotional, escalation, frustrated, confused, crisis step-down |
| Session isolation | 4 | Emotional state, frustration count don't leak |
| Unrecognized escalation | 7 | 3-tier redirect, sticky detection |

### `test_context_routing.py` — 101 tests

Context-aware routing, _last_action lifecycle, and implicit service change detection.

| Category | Tests | What's covered |
|---|---|---|
| last_action lifecycle | 15 | Set by context handlers, cleared by shifts |
| Confirm/deny routing | 12 | Re-extraction, service change detection |
| Yes/no after context | 10 | Emotional, escalation, frustration, confused |
| Frustration counter | 6 | Increment, escalation, reset |
| Emotional → service | 5 | Transition from emotional to service flow |
| Slot persistence | 4 | Slots survive across context changes |
| Complex flows | 6 | Multi-step conversations |
| Other-type interception | 2 | service_type="other" without detail |
| Implicit service change | 21 | Direct change (7), negation swap (3), additive intent (7), edge cases (4) |

### `test_phrase_audit.py` — 68 tests

Phrase list completeness, emotion-specific routing, and emotional enhancement validation.

| Category | Tests | What's covered |
|---|---|---|
| P0-P3 phrases | 18 | Frustration, emotional, confused, shame phrases |
| Emotion-specific | 6 | Scared, sad, rough_day, shame, grief, alone responses |
| Enhancement validation | 14 | Valid enhancements pass, NONE rejected, service push blocked, too-long rejected |
| Enhancement scaffold | 11 | Static response always present, no service mentions, navigator offer present |
| Blocklist gaps | 9 | Vague service hints blocked |
| Emotional+service collision | 3 | Emotional overrides service intent |
| Help override | 4 | "help" with emotional context routes to emotional |
| Shame prefix | 3 | Normalizing prefix on shame+service |

### `test_contraction_normalization.py` — 19 tests

Contraction expansion and intensifier stripping.

| Category | Tests | What's covered |
|---|---|---|
| Contraction expansion | 10 | 37 contractions, edge cases |
| Intensifier stripping | 9 | 20 adverbs × emotion matrix |

### `test_narrative_extraction.py` — 17 tests

Narrative detection, urgency hierarchy, and regex fallback.

| Category | Tests | What's covered |
|---|---|---|
| Detection | 3 | ≥20 words threshold, short messages excluded |
| Urgency hierarchy | 5 | shelter > medical > food > employment |
| Regex fallback | 4 | Re-ranking, context clues, urgency inference |
| Smart routing | 5 | Narrative vs simple in extract_slots_smart |

### `test_integration_scenarios.py` — 29 tests

End-to-end tests through the full `generate_reply` pipeline, reproducing eval scenario messages.

| Category | Tests | What's covered |
|---|---|---|
| Narrative integration | 7 | Hospital/housing, re-entry, eviction, runaway youth through full flow |
| Cross-feature | 4 | Emotional+narrative, shame+narrative, intensifiers+narrative, frustration→narrative |
| PII in narratives | 4 | Phone, name, SSN, multiple PII in long messages |
| Session isolation | 2 | Two sessions don't leak slots or emotional state |
| Eval approximations | 12 | Emotional (3), routing (3), narrative (3), adversarial (2), shame (1) |

### `test_bot_knowledge.py` — 62 tests

Bot self-knowledge module: live capability sourcing, topic matching, and LLM context generation.

| Category | Tests | What's covered |
|---|---|---|
| Live sourcing | 3 | Service categories, PII types, location count from code |
| Topic matching | 16 | All 15 topics + no-match case |
| Capability context | 6 | LLM prompt includes services, PII, locations, privacy, crisis, emotional |
| Static handler | 3 | Routes through bot_knowledge correctly |
| Phrase classification | 5 | New privacy phrases classify as bot_question |
| Untested topics | 6 | language, peer_navigator, privacy_delete/identity/police/visibility |
| Topic collisions | 5 | Priority ordering for multi-match messages |
| False positives | 10 | Non-questions don't match |
| Routing integration | 3 | End-to-end through generate_reply |

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
# Run all 114 scenarios
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py

# Run only crisis scenarios
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py --category crisis

# Run a single scenario and save JSON report
ANTHROPIC_API_KEY=sk-ant-... python tests/eval_llm_judge.py --scenario-id shelter_queens_17 --output eval_report.json
```

### Scenario coverage

114 scenarios across 21 categories: happy_path, multi_turn, crisis, confirmation, privacy, edge_case, natural_language, adversarial, accessibility, taxonomy_regression, borough_filter, no_result, staten_island, neighborhood_routing, schedule, referral, data_quality, emotional, bot_question, and guard (emotional+service overlap), multi_intent.

Notable additions: 2 frustration escalation scenarios (repeated frustration loop, frustration-to-resolution arc), and 10 scenarios informed by the WA Homelessness Portal covering rough sleepers, unsafe housing, family with children, substance use + shelter, dual needs, negative preferences, non-English speakers, youth runaways, privacy around data sharing, and multi-need storytelling.

**Multi-intent queue flow (30 scenarios)** — core queue (food+shelter sequential,
shower+food drop-in pattern, clothing+food), three-service combos (DYCD drop-in
trio, asylum seeker trio), queue decline (2 phrasings), location change mid-queue
(typed and button), cross-service slot conflicts (cross-borough, cross-neighborhood),
emotional+multi-service empathetic framing (4 tone variants + second-service warmth),
shame/embarrassment tone (3 — food bank stigma, shelter stigma, single-service
normalizing), YourPeer personas (LGBTQ youth/Ali Forney, DYCD RHY runaway,
foster care aging-out, asylum seeker, re-entry from Rikers, family with children
via PATH), queue edge cases (ignore queue with new request, start over clears
queue), and complex natural language (substance use narrative, outreach worker
referral).

## Known Limitations

These are documented behaviors, not bugs:

- **Bare numbers (regex only):** Replying with just "17" (no context like "I am" or "age") does not extract age with the regex extractor. LLM extraction handles this correctly when enabled.
- **Multi-intent:** "I need food and shelter" extracts all service types, searches the first, then offers remaining services sequentially via the queue. Known limitation: only one location is extracted per message — "food in Brooklyn and shelter in Manhattan" uses Brooklyn for both. User can correct via "change location" when the second service is offered. 30 eval scenarios cover this flow.
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
