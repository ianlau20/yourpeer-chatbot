# YourPeer Chatbot — Claude Code Context

## What This Project Is

A conversational chatbot for [YourPeer](https://yourpeer.nyc), built by Streetlives, that helps
unhoused New Yorkers find services (shelter, food, clothing, showers, benefits).

## Stack

| Layer | Tech |
|-------|------|
| LLM | Claude Sonnet |
| Backend | FastAPI (Python) |
| Frontend | React chat component |
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
    │   ├─ greeting/thanks/help/reset/escalation/frustration → canned response
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
| `backend/app/services/chatbot.py` | Core conversation engine: classification, slot merging, routing, confirmation flow |
| `backend/app/services/crisis_detector.py` | Two-stage crisis detection (regex + Sonnet LLM), category-specific hotlines |
| `backend/app/services/slot_extractor.py` | Regex-based slot extraction with keyword matching |
| `backend/app/services/llm_slot_extractor.py` | LLM slot extraction via Claude Haiku tool calling |
| `backend/app/services/session_store.py` | In-memory session state with 30-min TTL (max 500 sessions) |
| `backend/app/services/audit_log.py` | Anonymized event logging (capped ring buffer) |
| `backend/app/llm/claude_client.py` | Anthropic client (lazy init), model constants, shared helpers |
| `backend/app/rag/__init__.py` | `query_services()` entry point |
| `backend/app/rag/query_executor.py` | DB execution, location normalization, borough/neighborhood PostGIS logic |
| `backend/app/rag/query_templates.py` | 9 parameterized SQL templates (food, shelter, clothing, etc.) |
| `backend/app/privacy/pii_redactor.py` | PII detection and redaction (phone, SSN, email, DOB, address, names) |
| `backend/app/models/chat_models.py` | Pydantic models: ChatRequest, ChatResponse, ServiceCard, QuickReply |
| `frontend-next/src/components/chat/` | Chat UI components (ChatContainer, ServiceCard, QuickReplies) |
| `frontend-next/src/app/admin/` | Staff console pages (overview, conversations, evals) |
| `frontend-next/next.config.js` | API rewrites (`/api/chat` → backend `:8000`) |
| `tests/conftest.py` | Pytest fixtures, mock data, test helpers |
| `tests/eval_llm_judge.py` | LLM-as-judge evaluation (85 scenarios, 8 dimensions) |

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
- **PII redaction**: phone, SSN, email, DOB, address, name detection/redaction on every message
- **Service cards**: structured results with name, org, address, phone, hours, fees, open/closed status, referral badges, action links
- **Conversational routing**: greeting, thanks, help, reset, escalation, frustration, bot identity, confusion
- **LLM conversational fallback**: Haiku handles general/off-topic messages
- **Admin console**: conversation viewer, event log, metrics dashboard, in-browser eval runner
- **LLM-as-judge eval**: 85 scenarios scored on slot accuracy, dialog efficiency, tone, safety, confirmation UX, privacy, hallucination resistance, error recovery
- **Accessibility**: screen reader support, keyboard navigation, voice input (Web Speech API)
- **Anonymized audit logging**: conversation turns, query executions, crisis events
- **In-memory sessions**: no persistent conversation storage, 30-min TTL
- **Result sorting**: open-now first, then recently verified, then name; proximity-first when geolocation available
- **Error boundaries**: route-level (chat, admin, global) + component-level (ServiceCarousel) + custom 404
- **Test suite**: 15 pytest files covering all services, routes, and edge cases (no live API/DB needed)

## Known Gaps / In Progress

- **Multi-intent requests** — cannot handle "food AND shelter" in a single message
- **Real-time location** — browser geolocation supported (opt-in); falls back to text-based location when denied
- **Caching** — DB queries are not cached
- **Multilingual support** — English only
- **Adversarial service handling** — requests for impossible services proceed to search
- **Result ordering** — sorted by open now, then recently verified, then name; proximity-first when geolocation is available
- **Schedule data coverage** — sparse; only walk-in services have >40% coverage
- **`additional_info` field** — 99.7% null in DB, always empty in results
- **Eval runs in web server process** — background task can block request handling during long runs

## Running Tests

```bash
cd backend
source venv/bin/activate
pytest                                    # all tests (no API key or DB needed)
pytest tests/test_chatbot.py              # single file
pytest -k reset                           # filter by test name
```

All tests mock `claude_reply()` and `query_services()` — no live services required.
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
  `slot_extractor.py` (keywords), and `chatbot.py` (routing logic).
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
| `RATE_LIMIT_IP_PER_MIN` | No | Per-IP messages/minute (default: 60) |
| `RATE_LIMIT_IP_PER_HOUR` | No | Per-IP messages/hour (default: 300) |
| `RATE_LIMIT_FEEDBACK_PER_MIN` | No | Feedback requests per session/minute (default: 10) |
