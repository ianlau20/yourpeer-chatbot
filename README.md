# YourPeer Chatbot

A conversational interface that helps people experiencing homelessness find free services in New York City — food, shelter, clothing, showers, health care, legal help, and more.

Built by [Streetlives](https://www.streetlives.nyc/) as a front-end to the [YourPeer](https://yourpeer.nyc/) service directory.

## How It Works

A user describes what they need in plain language — by typing, tapping a quick-reply button, or using voice input. The chatbot extracts the service type and location through natural conversation, confirms the search parameters, then queries the Streetlives database and returns real, verified service listings as interactive cards — with addresses, hours, phone numbers, and links to the full YourPeer listing. The interface supports screen readers, keyboard navigation, and voice input for low-literacy and low-vision users.

```
User:  taps "🍽️ Food"
Bot:   "What neighborhood or borough are you in?"  [Manhattan] [Brooklyn] [Queens] [Bronx]
User:  taps "Brooklyn"
Bot:   "I'll search for food in Brooklyn."  [✅ Yes, search] [📍 Change location] [🔄 Change service]
User:  taps "✅ Yes, search"
Bot:   returns → 2 service cards with names, addresses, hours, and action buttons
```

**No hallucination by design.** The LLM handles conversation only — all service data comes from deterministic database queries using pre-reviewed templates. The bot never makes up service names, addresses, or eligibility rules.

## Quick Start

```bash
# Clone and set up backend
git clone https://github.com/ianlau20/yourpeer-chatbot.git
cd yourpeer-chatbot
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt

# Configure backend environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY and DATABASE_URL

# Run backend (Terminal 1)
cd backend
uvicorn app.main:app --reload

# Set up and run frontend (Terminal 2 — requires Node.js 18.18+)
cd frontend-next
npm install
echo "CHAT_BACKEND_URL=http://localhost:8000" > .env.local
npm run dev

# Open http://localhost:3000/chat   (chat interface)
# Open http://localhost:3000/admin  (staff review console)
```

See [SETUP.md](docs/SETUP.md) for detailed instructions including prerequisites, IDE configuration, and Render deployment.

## Architecture

```
User → Chat UI → FastAPI → Message Classifier → Slot Extraction → Confirmation → Query Templates → Streetlives DB
          ↑                      ↓                     ↓               ↓                                   ↓
   Quick-reply            Crisis Detection        PII Redaction    User confirms                      Service Cards
   buttons                (regex + Sonnet)            ↓          or changes slots                         ↓
                          → Step-down when       Session Store                                       YourPeer links
                            service intent           ↓
                          Greeting / Reset       Claude Haiku (fallback
                          Thanks / Help          for general conversation
                          Escalation             and DB failures only)
                          Frustration (AVR)
                          Emotional (AVR)
                          Bot identity
                          Confused/overwhelmed
                          Confirmation
                          handling

Staff → Admin Console (/admin) → Audit Log API → Anonymized transcripts, query logs, crisis events, stats
                                       ↓
                                  Eval Results → LLM-as-judge scores (from eval_llm_judge.py)
                                  Model Analysis → Per-task cost/capability analysis
```

The system follows a **Safer, Limited RAG** pattern with four phases:

1. **Intake** — Slot extraction collects structured fields (service type, location, age, urgency, gender) through multi-turn conversation. Multi-service extraction detects all services in a message ("I need food and shelter") and queues them for sequential search. Quick-reply buttons let users tap instead of type. Uses regex by default; when `ANTHROPIC_API_KEY` is set, a tiered approach runs regex first and calls Claude Haiku for complex or ambiguous inputs. Crisis detection runs on every message before anything else, using regex pre-check followed by Claude Sonnet LLM classification when regex misses — with an emotional phrase guard that prevents sub-crisis expressions ("feeling scared", "I'm struggling") from being over-escalated to crisis. When crisis fires alongside service intent, a step-down flow shows crisis resources while preserving the service context. The message classifier routes greetings, resets, escalation, frustration, bot-identity questions, confusion, and help before slot extraction runs. Emotional handling follows the Acknowledge-Validate-Redirect (AVR) pattern from clinical chatbot research. PII is redacted from stored transcripts.
2. **Confirmation** — When service type and location are filled, the bot summarizes the search ("I'll search for food in Brooklyn") and presents quick-reply options: confirm, change location, change service, or start over. The database is only queried after explicit user confirmation.
3. **Query** — Pre-defined, parameterized SQL templates run against the Streetlives PostgreSQL database. Borough-level queries use the `pa.borough` column directly — more reliable than expanding city name lists. Neighborhood queries use PostGIS proximity search (`ST_DWithin`) with coordinates for 59 NYC neighborhoods. If the strict query returns no results, filters are automatically relaxed while keeping location boundaries. Data-informed nearby borough suggestions are offered when results are thin.
4. **Rendering** — Results are returned as structured service cards, never as LLM-generated text. Cards include address, hours, phone, fees, a "Referral may be required" badge for membership-gated services, and direct links to YourPeer.

## Features

See [FEATURES.md](docs/FEATURES.md) for the full feature reference, organized by area: conversation & intake, crisis detection, search & results, service cards, privacy & safety, accessibility, and staff tools.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Slot Extraction | Regex (default) + Claude Haiku via Anthropic API (for complex inputs) |
| Crisis Detection | Regex pre-check + Claude Sonnet (LLM stage for nuanced/indirect language) |
| Conversational Fallback | Claude Haiku (dialog only, not for service data) |
| Database | Streetlives PostgreSQL on AWS RDS (read-only), PostGIS for neighborhood proximity |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS, Zustand, Radix UI, Lucide icons |
| Deployment | Render (two services: FastAPI API + Next.js frontend) |

## Models

Two Claude models are used across the system, each assigned to specific tasks based on a cost/capability analysis (see the Model Analysis tab in the admin panel). None of them generate service data. Model selection is centralized in `backend/app/llm/claude_client.py`.

### Claude Haiku (`claude-haiku-4-5-20251001`)

**Used for:** Conversational fallback and slot extraction.

**Conversational fallback** — General responses to messages that don't match any routing category and don't contain service slots. Only runs when all other routing paths have been exhausted. The vast majority of messages never reach the LLM. It handles genuinely open-ended conversational turns: a user telling a story before stating their need, an ambiguous follow-up after results are delivered, or a message the classifier couldn't route. Also used as a database fallback — if a database query throws an exception, the bot calls Haiku with a prompt asking it to acknowledge the issue and keep the user engaged. Haiku never generates service data. Its system prompt explicitly prohibits fabricating service names, addresses, or phone numbers.

**Slot extraction** — Extracting structured fields (service type, location, age, urgency, gender) from natural language. Only runs for messages classified as "complex" by a lightweight complexity check. Simple, clear requests ("I need food in Brooklyn") are handled by regex alone. Haiku runs for long messages, implicit needs, slang, or conflicting signals. Uses the `extract_intake_slots` tool with a strict JSON schema — the model is constrained to return only the defined fields and enum values.

**Why Haiku:** Speed. Haiku is 4-5x faster than Sonnet, which directly improves chat UX for real-time conversation. Both tasks have simple output constraints (1-3 sentences for conversation, 5-field JSON for slots) where Sonnet's deeper reasoning adds no measurable value.

**Requires:** `ANTHROPIC_API_KEY` in `.env`.

---

### Claude Sonnet (`claude-sonnet-4-6`)

**Used for:** Crisis detection (Stage 2 LLM classification) and LLM-as-judge evaluation.

**Crisis detection** — Only invoked when the regex pre-check returns no match. Clear crisis language ("I want to kill myself") is caught by regex in <1ms and never reaches the LLM. Sonnet handles indirect and paraphrased expressions — "I've been on the streets for months and nothing helps anymore", "no one would notice if I disappeared." `max_tokens` is capped at 60 — the JSON response (`{"crisis": true, "category": "..."}`) is about 15 tokens.

**Why Sonnet for crisis:** This is a safety-critical classification where false negatives have real consequences for vulnerable people. Sonnet's adaptive thinking adjusts reasoning depth to ambiguity, which is exactly what's needed for indirect crisis language. The volume is very low (~5% of turns reach the LLM stage) so the 3x cost premium over Haiku adds negligible total cost.

**Fail-open:** If the Sonnet call fails for any reason, the system returns a general safety response rather than falling through to normal conversation. See [CRISIS_DETECTION.md](docs/CRISIS_DETECTION.md) for full details.

**LLM-as-judge** — `eval_llm_judge.py` uses Sonnet to score conversations across 8 dimensions. This runs only during evaluation, not in production.

**Requires:** `ANTHROPIC_API_KEY` in `.env`. If absent, the LLM crisis detection stage is disabled and only regex detection runs.

**When it runs:** Only when the eval suite is triggered manually — either via `python tests/eval_llm_judge.py` on the command line or via the "Run Evals" button in the admin console. Never runs during normal user interactions.

**Not part of the production system.** The eval runner is a development and QA tool. It consumes API quota but has no effect on conversations.

## Known Limitations & Future Work

These are tracked issues identified during DB audits and pilot testing, deferred for post-pilot resolution.

**Result ordering.** Results are sorted by: (1) open now — services currently open appear first, (2) recently verified — freshest data via `l.last_validated_at DESC NULLS LAST`, (3) service name as a stable tiebreaker. When browser geolocation is available, distance is the primary sort with open-now and freshness as secondary tiebreakers.

**`additional_info` field is effectively empty.** DB audit (Apr 2026) shows 3,240 of 3,251 services (99.7%) have no `additional_info`. The field is selected in the base query and rendered conditionally in the card, but it adds negligible value. Consider removing it from the SELECT in a future query optimization pass to reduce payload size.

**Schedule data is sparse for most categories.** Only walk-in service types (Soup Kitchen 81%, Shower 55%, Clothing Pantry 64%, Food Pantry 40%) have meaningful schedule coverage. All other categories show 0% coverage. The `FILTER_BY_OPEN_NOW` and `FILTER_BY_WEEKDAY` query filters exist but are intentionally not passed from the chatbot — enabling them would silently exclude the majority of services. See `METRICS.md` section 2.4 for detail.

**Eval runs share the web server host.** The "Run Evals" button runs the LLM-as-judge suite in a subprocess (isolated from request handling via `asyncio.create_subprocess_exec`), but it still runs on the same machine as the web server. Acceptable for the pilot; for production, isolate into a separate worker or task queue to avoid resource contention during long runs.

## Documentation

| Document | Description |
|---|---|
| [FEATURES.md](docs/FEATURES.md) | Full feature reference — conversation & intake, crisis detection, search & results, service cards, privacy & safety, staff tools |
| [CHATBOT_BEHAVIOR.md](docs/CHATBOT_BEHAVIOR.md) | Chatbot behavior — routing pipeline, message categories, emotional handling design (AVR pattern), crisis step-down, LLM usage, guardrails, conversation modes, limitations, how to extend |
| [CRISIS_DETECTION.md](docs/CRISIS_DETECTION.md) | Crisis detection — two-stage architecture, category definitions, fail-open policy, emotional phrase guard, crisis step-down, phrase list design, LLM prompt, and how to extend |
| [PII_REDACTION.md](docs/PII_REDACTION.md) | PII redaction — six detection categories, pattern details, tradeoffs, known gaps, and future improvements |
| [METRICS.md](docs/METRICS.md) | Success metrics — 24+ metrics across 6 layers with definitions, targets, measurement methods, and pilot vs. post-pilot phasing |
| [EVAL_RESULTS.md](docs/EVAL_RESULTS.md) | Eval history — per-scenario scores, critical failures, and fixes across all 17 runs |
| [SETUP.md](docs/SETUP.md) | Local development setup — virtual environment, dependencies, API keys, running locally |
| [DEPLOY.md](docs/DEPLOY.md) | Render deployment — environment variables, build commands, auto-deploy, starter tier notes |
| [TESTING.md](docs/TESTING.md) | Test suite guide — 969 tests across 23 files + 142-scenario LLM-as-judge evaluation framework |
| [scripts/DB_AUDIT.md](scripts/DB_AUDIT.md) | Database audit script — why it exists, how to run it, when to run it, and how to interpret results |

## Related Repositories

| Repo | Description |
|---|---|
| [streetlives/yourpeer.nyc](https://github.com/streetlives/yourpeer.nyc) | The YourPeer web application (Next.js) |
| [streetlives/chat-poc](https://github.com/streetlives/chat-poc) | Original chat proof-of-concept with database schema exploration |

## License

Copyright © 2026 Streetlives, Inc.
