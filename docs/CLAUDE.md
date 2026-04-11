# YourPeer Chatbot — Claude Code Context

## What This Project Is

A conversational chatbot for [YourPeer](https://yourpeer.nyc), built by Streetlives, that helps
unhoused New Yorkers find services (shelter, food, clothing, showers, benefits).

## Stack

| Layer | Tech |
|-------|------|
| LLM | Claude Haiku + Sonnet |
| Backend | FastAPI (Python) |
| Frontend | Next.js 15 / React 19 / Zustand |
| Database | Streetlives PostgreSQL (read-only) |

**Architecture:** `User → Chat UI → Backend → LLM + Query Templates → Streetlives API`

---

## Current State

A fully functional multi-turn chatbot that guides users through service discovery via
slot-filling conversation. The system uses a two-stage classification pipeline (regex first,
LLM fallback) to route messages, extracts service needs (type, location, age, urgency, gender),
confirms with the user, then queries a read-only Streetlives PostgreSQL database using
parameterized SQL templates. Results are returned as structured service cards with contact info,
hours, and directions links. Crisis detection, PII redaction, and an admin console with
LLM-as-judge evaluation are all implemented. The system works in a degraded but functional
regex-only mode when no API key is configured.

## Architecture (Actual)

```
User Message
  → POST /chat/ (FastAPI)
  → chatbot.generate_reply()
    ├─ PII redaction (every message)
    ├─ Message classification (2-stage: regex → LLM fallback)
    ├─ Route by category:
    │   ├─ crisis → crisis_detector (regex + Sonnet LLM) → hotline resources
    │   ├─ correction → clears pending state, shows alternatives
    │   ├─ negative_preference → acknowledges rejection, offers alternatives
    │   ├─ greeting/thanks/help/reset/escalation → canned response
    │   ├─ frustration → 3-tier escalation (counter-based, varied responses)
    │   ├─ emotional → static emotion-specific response (no LLM, 6 emotion keys)
    │   ├─ post-results → deterministic answers from stored cards (no LLM)
    │   ├─ disambiguation → clarifying options when intent is ambiguous
    │   ├─ service request → slot extraction (regex or Haiku LLM for complex inputs)
    │   │   ├─ slots incomplete → follow-up question
    │   │   ├─ slots complete → confirmation prompt with quick replies
    │   │   └─ confirmed → query_services() → SQL template → DB → service cards
    │   └─ general → LLM conversational fallback (Haiku)
    ├─ Session state saved (in-memory, 30-min TTL)
    ├─ Audit log entry
    └─ Return ChatResponse (response text, slots, service cards, quick replies)
```

All service data comes from deterministic DB queries — the LLM never generates service
information, preventing hallucination.

## Key Files & Structure

| File | Purpose |
|------|---------|
| `backend/app/main.py` | FastAPI app entry point, CORS, router registration |
| `backend/app/routes/chat.py` | `POST /chat/` and `/chat/feedback` endpoints |
| `backend/app/routes/admin.py` | Admin API: conversations, events, stats, eval runner |
| `backend/app/services/chatbot.py` | Conversation router: `generate_reply()`, query execution, session orchestration |
| `backend/app/services/classifier.py` | Message classification: `_classify_action()`, `_classify_tone()`, contraction normalization, intensifier stripping |
| `backend/app/services/phrase_lists.py` | All keyword/phrase lists, quick-reply definitions, service labels, borough suggestion data |
| `backend/app/services/responses.py` | Response strings, emotion-specific responses, LLM prompt builders, bot-question answers |
| `backend/app/services/confirmation.py` | Confirmation messages, quick-reply builders, no-results messages, borough suggestions |
| `backend/app/services/bot_knowledge.py` | Bot self-knowledge: live capability sourcing, topic matching, LLM context generation |
| `backend/app/services/crisis_detector.py` | Two-stage crisis detection (regex + Sonnet LLM), category-specific hotlines |
| `backend/app/services/slot_extractor.py` | Regex-based slot extraction with keyword matching, gender/LGBTQ identity extraction |
| `backend/app/services/llm_slot_extractor.py` | LLM slot extraction via Claude Haiku tool calling |
| `backend/app/services/llm_classifier.py` | Unified LLM classification gate — single Haiku call returning service_type, location, tone, action when regex fails |
| `backend/app/services/session_store.py` | In-memory session state with 30-min TTL (max 500 sessions) |
| `backend/app/services/audit_log.py` | Anonymized event logging (capped ring buffer), P0-P3 metrics aggregation (confidence, recovery rates, session metrics, no-result by service, time-of-day, geographic demand, frustration tiers, session duration, repetition rate, LLM call metrics) |
| `backend/app/llm/claude_client.py` | Anthropic client (lazy init), model constants, shared helpers |
| `backend/app/rag/__init__.py` | `query_services()` entry point |
| `backend/app/rag/query_executor.py` | DB execution, location normalization, borough/neighborhood PostGIS logic |
| `backend/app/rag/query_templates.py` | 9 parameterized SQL templates (food, shelter, clothing, etc.) |
| `backend/app/privacy/pii_redactor.py` | PII detection and redaction (phone, SSN, email, DOB, address, names, gender identity) |
| `backend/app/models/chat_models.py` | Pydantic models: ChatRequest, ChatResponse, ServiceCard, QuickReply |
| `frontend-next/src/components/chat/` | Chat UI components (ChatContainer, ServiceCard, QuickReplies) |
| `frontend-next/src/lib/chat/store.ts` | Zustand chat store with `localStorage` persistence |
| `frontend-next/src/lib/admin/store.ts` | Zustand admin store with staleness-based caching |
| `frontend-next/src/app/admin/` | Staff console pages (overview, conversations, metrics, queries, evals, models) |
| `frontend-next/next.config.js` | CSP + HSTS headers, security config |
| `tests/conftest.py` | Pytest fixtures, mock data, test helpers |
| `tests/eval_llm_judge.py` | LLM-as-judge evaluation (142 scenarios, 8 dimensions) |

## What's Working

- **9 service categories**: food, shelter, clothing, personal care, medical, mental health, legal, employment, other
- **Multi-turn slot-filling**: extracts service_type, location, age, urgency, gender across conversation turns
- **Two-stage classification**: regex for fast deterministic routing, LLM for ambiguous messages
- **Complexity-based LLM routing**: regex handles simple inputs, Claude Haiku handles complex/implicit/slang
- **Confirmation step**: user confirms before any DB query executes
- **Quick-reply buttons**: welcome categories, borough selection, geolocation ("Use my location"), confirmation actions
- **Browser geolocation**: opt-in "Use my location" via Geolocation API; falls back to borough buttons on denial
- **Borough + neighborhood search**: direct borough column filter or PostGIS proximity (59 NYC neighborhoods)
- **Relaxed fallback**: auto-broadens filters when 0 results, suggests boroughs with more data
- **Crisis detection**: regex + Sonnet LLM, covers suicide/self-harm, DV, trafficking, medical emergency, violence, youth runaway; fail-open policy returns safety response if LLM unavailable
- **PII redaction**: phone, SSN, email, DOB, address, name, gender identity detection/redaction on every message
- **Service cards**: structured results with name, org, address, phone, hours, fees, open/closed status, referral badges, action links
- **Gender & LGBTQ identity filtering**: extracted only when explicitly stated (never inferred). Binary gender (male/female) passes to SQL filter. Transgender/nonbinary/LGBTQ bypass the eligibility filter and trigger taxonomy boosts for affirming services. Confirmation shows "LGBTQ-friendly" label. Gender terms redacted from stored transcripts
- **Conversational routing**: greeting, thanks, help, reset, escalation, frustration, emotional, negative preference, bot identity, confusion, location-unknown, correction
- **Emotional handling (static-first)**: 6 emotion-specific static responses (scared, sad, rough_day, shame, grief, alone) selected by `_pick_emotional_response()` — LLM is NOT called. Single "Talk to a person" button, no service menu. Follows AVR pattern from clinical chatbot research
- **Frustration 3-tier escalation**: persistent `_frustration_count` counter with varied responses — 1st: full empathetic, 2nd: shorter/direct, 3rd+: immediate navigator only. Counter survives intermediate messages
- **Negative preference handling**: detects rejection of all offered options ("none of those", "not what I need" — 19 phrases). Acknowledges rejection explicitly, offers alternative service categories + peer navigator
- **Conversational awareness guard**: casual chat patterns ("how are you", "just wanted to chat") suppress service category buttons. Prevents first-turn casual greetings from showing the full service menu
- **Privacy routing exception**: `bot_question` overrides `has_service_intent` in routing — privacy questions like "do they get my info?" aren't swallowed by the service flow even when service keywords are present
- **Intensifier stripping**: `_strip_intensifiers()` removes 19 common adverbs (really, very, so, just, etc.) before phrase matching. Combined with contraction normalization, `_classify_tone()` checks 4 variants per message
- **Post-normalization emotional phrases**: `_EMOTIONAL_PHRASES` includes both contraction ("i'm scared") and expanded ("i am scared") forms for 13 emotional states (135 total phrases)
- **Location-unknown interceptor**: when the bot asks for location and the user says "I don't know" / "anywhere" / "here", offers geolocation and borough buttons instead of falling into the confused handler. Guards: only fires when service_type is set, location is missing, and no pending confirmation
- **Service flow continuation**: when a user already has a service_type and provides new slot data (e.g., "near me", "close by", "I'm 25", "with my kids") in a message not classified as "service", the system treats it as a service flow continuation rather than falling through to the LLM
- **Narrative extraction**: long messages (20+ words) are detected as narratives and processed with urgency-aware slot extraction that prioritizes shelter/safety over food/employment. Regex fallback handles narrative extraction when LLM is unavailable
- **Bot self-knowledge**: live capability sourcing from actual code (service categories, PII types, location count) rather than hardcoded facts. Topic matching for 12+ question types with LLM context generation
- **Confidence scoring**: every routing decision is tagged with a confidence level (high/medium/low/disambiguated) and stored in audit events. Regex matches = high, LLM classification = medium, fallback = low
- **Disambiguation prompts**: when a message is ambiguous between a post-results question and a new service request, the bot asks the user to clarify instead of guessing. Presents quick-reply buttons for both interpretations
- **"Not what I meant" recovery**: correction phrases ("not what I meant", "you misunderstood") trigger a handler that clears pending state, shows what the bot was doing, and offers alternatives. "❌ Not what I meant" button appears on low-confidence responses
- **Post-results escape hatch**: new service requests ("I need X", "where can I go", "looking for") are no longer intercepted by the post-results handler. Messages with a new location clear stored results automatically
- **LLM conversational fallback**: Haiku handles general/off-topic messages
- **Admin console**: conversation viewer, event log, metrics dashboard, in-browser eval runner
- **LLM-as-judge eval**: 142 scenarios scored on slot accuracy, dialog efficiency, tone, safety, confirmation UX, privacy, hallucination resistance, error recovery
- **Accessibility**: screen reader support, keyboard navigation, voice input (Web Speech API)
- **Anonymized audit logging**: conversation turns, query executions, crisis events
- **In-memory sessions**: no persistent conversation storage, 30-min TTL, LRU eviction at 500-session cap
- **Chat history persistence**: conversation survives page refresh via Zustand `localStorage` sync; auto-resets after 30-min inactivity to match backend TTL
- **Result sorting**: open-now first, then recently verified, then name; proximity-first when geolocation available
- **Error boundaries**: route-level (chat, admin, global) + component-level (ServiceCarousel) + custom 404
- **Security**: CORS allowlist, CSRF middleware, HMAC-signed session tokens, admin API key auth, CSP/X-Frame-Options/Permissions-Policy headers, eval subprocess isolation
- **Stability**: 1,000-char message length limit (frontend + backend), coordinate validation (lat ±90, lng ±180), 10s LLM timeout, 5s DB statement timeout, 30s frontend fetch timeout, admin endpoint rate limiting (120/min IP + 5/hr eval), rate limiter memory cap (5,000 buckets)
- **Observability**: `X-Request-ID` correlation IDs flow from frontend → Next.js proxy → FastAPI backend → audit log, enabling end-to-end request tracing
- **Admin data caching**: centralized Zustand store with 30-second staleness threshold; navigating between admin tabs reuses cached data
- **Test suite**: 39 pytest files (1,475 tests) organized into `tests/unit/` (23 files — no DB or LLM needed) and `tests/integration/` (15 files — use mocked DB/LLM), plus an `eval/` directory. Covers all services, routes, edge cases, geolocation, rate limiting, security, privacy, family composition, multi-service extraction, split classifier, taxonomy enrichment, nearby borough suggestions, gender/LGBTQ identity extraction, bug fix regressions, narrative extraction, bot knowledge, boundary drift detection, context routing, integration scenarios, ambiguity handling (confidence scoring, disambiguation, correction recovery), post-results boundary routing, and DB schema/query integration. LLM-as-judge evaluation: 142 scenarios across 20 categories

## Known Gaps / In Progress

- **Adversarial LLM false positives** — The unified classification gate classifies nonsensical service requests ("helicopter ride") as `service_type=other` instead of returning null. Fix: tighten the LLM prompt to restrict "other" to known social service subcategories. Priority for Run 24.
- **Slot overwrite on contradiction** — `multiturn_change_mind` (3.25): when user says "actually, shelter" mid-conversation, the filled slot is not overwritten. Requires contradiction detection.
- **Multi-intent: per-service location** — Phase 4 per-service location binding is implemented but `multi_cross_borough` (3.88) shows it doesn't fire in all cases. Needs investigation.
- **Multilingual support** — English only
- **Schedule data coverage** — sparse; only walk-in services have >40% coverage
- **`additional_info` field** — 99.7% null in DB, always empty in results
- **LLM call instrumentation** — `log_llm_call()` API is defined in audit_log.py but not yet wired into `claude_client.py` call sites. Metrics section shows "No data" until instrumentation is added.
- **Persistent storage** — when `PILOT_DB_PATH` is set, audit events and sessions are persisted to SQLite (WAL mode) and hydrated on startup. When unset, in-memory only

## Running Tests

```bash
cd backend
source venv/bin/activate
pytest                                    # all tests (no API key or DB needed)
pytest tests/unit/                        # fast unit tests only
pytest tests/integration/                 # integration tests (mocked DB/LLM)
pytest tests/unit/test_slot_extractor.py  # single file
pytest -k reset                           # filter by test name
```

All tests mock `claude_reply()` and `query_services()` — no live services required.
Tests are organized into `tests/unit/` (23 files, no external deps) and `tests/integration/` (15 files, use `send()`/`send_multi()` helpers).
Shared fixtures and helpers live in `tests/conftest.py` (use `send()`, `send_multi()`,
`assert_classified()`). For live LLM integration tests:

```bash
ANTHROPIC_API_KEY=... pytest tests/test_llm_slot_extractor.py -k live
```

## Code Conventions

- **Two-stage pattern**: classification, slot extraction, and crisis detection all use
  regex first, LLM second. Regex handles the common/obvious cases fast; LLM catches
  ambiguous inputs. New detection features should follow this same pattern.
- **No LLM-generated service data**: the LLM handles conversation only. All service
  results come from parameterized SQL templates in `query_templates.py`. Never let the
  LLM produce service names, addresses, or phone numbers.
- **Fail-open for safety**: if the LLM is unavailable during crisis detection, the system
  returns a safety response with hotline numbers rather than falling through to normal
  conversation.
- **Model constants** are centralized in `claude_client.py` — don't hardcode model IDs
  elsewhere.

## Common Pitfalls

- Editing slot extraction logic without updating both `slot_extractor.py` (regex) **and**
  `llm_slot_extractor.py` (LLM) — they must stay in sync on supported slot names/values.
- Adding a new service category requires updates in `query_templates.py` (SQL template),
  `slot_extractor.py` (keywords), and `phrase_lists.py` (service label).
- Adding a new phrase list or keyword goes in `phrase_lists.py`, not `chatbot.py`.
  Classification logic is in `classifier.py`, response strings in `responses.py`,
  confirmation logic in `confirmation.py`.
- The DB is **read-only** — never add write queries.
- `conftest.py` defines mock data used across all test files. If you change response
  shapes (e.g. `ChatResponse` fields), update the mocks there too.

## Running Locally

See `docs/SETUP.md` for full instructions.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string for Streetlives DB |
| `ANTHROPIC_API_KEY` | Yes (for full features) | Enables LLM classification, slot extraction, crisis detection, and conversational fallback. System works in regex-only mode without it. |
| `CHAT_BACKEND_URL` | No | Frontend → backend URL (defaults to `http://localhost:8000`, set to Render URL in prod) |
| `RATE_LIMIT_SESSION_PER_MIN` | No | Per-session messages/minute (default: 12) |
| `RATE_LIMIT_SESSION_PER_HOUR` | No | Per-session messages/hour (default: 60) |
| `RATE_LIMIT_SESSION_PER_DAY` | No | Per-session messages/day (default: 200) |
| `RATE_LIMIT_IP_PER_MIN` | No | Per-IP messages/minute (default: 30) |
| `RATE_LIMIT_IP_PER_HOUR` | No | Per-IP messages/hour (default: 150) |
| `RATE_LIMIT_IP_PER_DAY` | No | Per-IP messages/day (default: 500) |
| `RATE_LIMIT_FEEDBACK_PER_MIN` | No | Feedback requests per session/minute (default: 10) |
| `SESSION_SECRET` | Yes (prod) | HMAC key for signing session tokens. If unset, tokens are unsigned (dev mode) |
| `ADMIN_API_KEY` | Yes (prod) | Bearer token required for all `/admin/api/*` endpoints. If unset, admin is open (dev mode) |
| `CORS_ALLOWED_ORIGINS` | Yes (prod) | Comma-separated list of allowed origins for CORS. If unset, allows all origins (dev mode) |
