# YourPeer Chatbot

A conversational interface that helps people experiencing homelessness find free services in New York City — food, shelter, clothing, showers, health care, legal help, and more.

Built by [Streetlives](https://www.streetlives.nyc/) as a front-end to the [YourPeer](https://yourpeer.nyc/) service directory.

## How It Works

A user describes what they need in plain language — or taps a quick-reply button. The chatbot extracts the service type and location through natural conversation, confirms the search parameters, then queries the Streetlives database and returns real, verified service listings as interactive cards — with addresses, hours, phone numbers, and links to the full YourPeer listing.

```
User:  taps "🍽️ Food"
Bot:   "What neighborhood or borough are you in?"  [Manhattan] [Brooklyn] [Queens] [Bronx]
User:  taps "Brooklyn"
Bot:   "I'll search for food in Brooklyn."  [✅ Yes, search] [📍 Change location] [🔄 Change service]
User:  taps "✅ Yes, search"
Bot:   returns → 2 service cards with names, addresses, hours, and action buttons
```

**No hallucination by design.** The LLM handles conversation only — all service data comes from deterministic database queries using pre-reviewed templates. The bot never makes up service names, addresses, or eligibility rules.

## Architecture

```
User → Chat UI → FastAPI → Message Classifier → Slot Extraction → Confirmation → Query Templates → Streetlives DB
          ↑                      ↓                     ↓               ↓                                   ↓
   Quick-reply            Crisis Detection        PII Redaction    User confirms                      Service Cards
   buttons                (regex + LLM)               ↓          or changes slots                         ↓
                          Greeting / Reset        Session Store                                       YourPeer links
                          Thanks / Help                ↓
                          Escalation             Gemini LLM (fallback
                          Frustration            for general conversation
                          Bot identity           and DB failures only)
                          Confused/overwhelmed
                          Confirmation
                          handling

Staff → Admin Console (/admin/) → Audit Log API → Anonymized transcripts, query logs, crisis events, stats
                                       ↓
                                  Eval Results → LLM-as-judge scores (from eval_llm_judge.py)
```

The system follows a **Safer, Limited RAG** pattern with four phases:

1. **Intake** — Slot extraction collects structured fields (service type, location, age, urgency, gender) through multi-turn conversation. Quick-reply buttons let users tap instead of type. Uses regex by default; when `ANTHROPIC_API_KEY` is set, a tiered approach runs regex first and calls Claude Sonnet for complex or ambiguous inputs. Crisis detection runs on every message before anything else, using regex pre-check followed by Claude Haiku LLM classification when regex misses. The message classifier routes greetings, resets, escalation, frustration, bot-identity questions, confusion, and help before slot extraction runs. PII is redacted from stored transcripts.
2. **Confirmation** — When service type and location are filled, the bot summarizes the search ("I'll search for food in Brooklyn") and presents quick-reply options: confirm, change location, change service, or start over. The database is only queried after explicit user confirmation.
3. **Query** — Pre-defined, parameterized SQL templates run against the Streetlives PostgreSQL database. Borough-level queries use the `pa.borough` column directly — more reliable than expanding city name lists. Neighborhood queries use PostGIS proximity search (`ST_DWithin`) with coordinates for 59 NYC neighborhoods. If the strict query returns no results, filters are automatically relaxed while keeping location boundaries. Data-informed nearby borough suggestions are offered when results are thin.
4. **Rendering** — Results are returned as structured service cards, never as LLM-generated text. Cards include address, hours, phone, fees, a "Referral may be required" badge for membership-gated services, and direct links to YourPeer.

## Features

See [FEATURES.md](FEATURES.md) for the full feature reference, organized by area: conversation & intake, crisis detection, search & results, service cards, privacy & safety, and staff tools.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Slot Extraction | Regex (default) + Claude Sonnet via Anthropic API (optional, for complex inputs) |
| Crisis Detection | Regex pre-check + Claude Haiku (LLM stage, when ANTHROPIC_API_KEY is set) |
| Conversational Fallback | Google Gemini (dialog only, not for service data) |
| Database | Streetlives PostgreSQL on AWS RDS (read-only), PostGIS for neighborhood proximity |
| Frontend | Vanilla HTML/CSS/JS with service card carousel |
| Deployment | Render (free tier) |

## Models

Four models are used across the system. Each has a specific, bounded role — none of them generate service data.

### Claude Haiku (`claude-haiku-4-5-20251001`)

**Used for:** Crisis detection — Stage 2 LLM classification.

**When it runs:** Only when the regex pre-check returns no match. Clear crisis language ("I want to kill myself") is caught by regex in <1ms and never reaches the LLM. The LLM handles indirect and paraphrased expressions that can't be enumerated — "I've been on the streets for months and nothing helps anymore", "no one would notice if I disappeared."

**Why Haiku:** Latency. Crisis detection is on the critical path for every message that bypasses regex. Haiku is the fastest available Claude model. `max_tokens` is capped at 60 — the JSON response (`{"crisis": true, "category": "..."}`) is about 15 tokens.

**Fail-open:** If the Haiku call fails for any reason, the system returns a general safety response rather than falling through to normal conversation. See [CRISIS_DETECTION.md](CRISIS_DETECTION.md) for full details.

**Requires:** `ANTHROPIC_API_KEY` in `.env`. If absent, the LLM stage is disabled and only regex detection runs.

---

### Claude Sonnet (`claude-sonnet-4-20250514`)

**Used for:** Slot extraction — extracting structured fields (service type, location, age, urgency, gender) from natural language messages.

**When it runs:** Only for messages classified as "complex" by a lightweight complexity check. Simple, clear requests ("I need food in Brooklyn") are handled by regex alone. Sonnet runs for long messages, implicit needs, slang, multi-part sentences, or conflicting signals — "I just got out of the hospital and need somewhere to stay", "my son is 12 and needs a coat, we're in Flatbush."

**Why Sonnet:** Accuracy. Slot extraction errors cascade — a wrong service type means wrong results. The complexity check routes only the cases where regex is likely to fail, so Sonnet is invoked selectively rather than on every message.

**Tool calling:** Uses the `extract_intake_slots` function with a strict JSON schema. The model is constrained to return only the defined fields and enum values — it cannot fabricate service types or locations not in the schema.

**Requires:** `ANTHROPIC_API_KEY` in `.env`. If absent, all slot extraction uses regex only.

---

### Gemini (`GEMINI_MODEL` env var, e.g. `gemini-2.0-flash`)

**Used for:** Conversational fallback — general responses to messages that don't match any routing category and don't contain service slots.

**When it runs:** Only when all other routing paths have been exhausted. The vast majority of messages never reach Gemini. It handles genuinely open-ended conversational turns: a user telling a story before stating their need, an ambiguous follow-up after results are delivered, or a message the classifier couldn't route.

**What it cannot do:** Gemini never generates service data. It receives a system prompt that explicitly prohibits fabricating service names, addresses, or phone numbers, and instructs it to steer the user toward stating their need and location so the database can be queried. All real service information comes from deterministic SQL templates.

**Also used as:** Database fallback. If a database query throws an exception, the bot calls Gemini with a prompt asking it to acknowledge the issue and keep the user engaged — rather than showing a raw error.

**Requires:** `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`. Both are required — the service will not start without them.

---

### LLM-as-Judge (eval only, `claude-sonnet-4-20250514`)

**Used for:** Automated evaluation — `eval_llm_judge.py` uses Claude Sonnet to score conversations across 8 dimensions (slot extraction accuracy, dialog efficiency, response tone, safety & crisis handling, confirmation UX, privacy protection, hallucination resistance, error recovery).

**When it runs:** Only when the eval suite is triggered manually — either via `python tests/eval_llm_judge.py` on the command line or via the "Run Evals" button in the admin console. Never runs during normal user interactions.

**Not part of the production system.** The eval runner is a development and QA tool. It consumes API quota but has no effect on conversations.

## Quick Start

```bash
# Clone and set up
git clone https://github.com/ianlau20/yourpeer-chatbot.git
cd yourpeer-chatbot
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your GEMINI_API_KEY, GEMINI_MODEL, and DATABASE_URL
# Optional: add ANTHROPIC_API_KEY for LLM-enhanced slot extraction and crisis detection

# Run
cd backend
uvicorn app.main:app --reload

# Open http://127.0.0.1:8000        (chat interface)
# Open http://127.0.0.1:8000/admin/  (staff review console)
```

See [SETUP.md](SETUP.md) for detailed instructions including IDE configuration and troubleshooting.

## Known Limitations & Future Work

These are tracked issues identified during DB audits and pilot testing, deferred for post-pilot resolution.

**Result ordering favors large organizations.** The base query orders results alphabetically by `o.name, s.name`. Large systems like NYC Health + Hospitals or CAMBA have many services per borough and will consistently appear at the top of results, crowding out smaller community organizations. A better ordering strategy — randomized within results, or weighted by data completeness (has phone, has hours, recently verified) — would give users more varied and actionable results.

**`additional_info` field is effectively empty.** DB audit (Apr 2026) shows 3,240 of 3,251 services (99.7%) have no `additional_info`. The field is selected in the base query and rendered conditionally in the card, but it adds negligible value. Consider removing it from the SELECT in a future query optimization pass to reduce payload size.

**Schedule data is sparse for most categories.** Only walk-in service types (Soup Kitchen 81%, Shower 55%, Clothing Pantry 64%, Food Pantry 40%) have meaningful schedule coverage. All other categories show 0% coverage. The `FILTER_BY_OPEN_NOW` and `FILTER_BY_WEEKDAY` query filters exist but are intentionally not passed from the chatbot — enabling them would silently exclude the majority of services. See `METRICS.md` section 2.4 for detail.

**Eval background task runs in the web server process.** The "Run Evals" button in the admin console triggers the LLM-as-judge suite as a FastAPI background task in the same process. Acceptable for the pilot; for production, isolate into a separate worker or task queue (Celery + Redis, or a Render background worker service) to avoid impacting request latency during long runs.

**`natural_new_to_nyc` slot extraction failure.** A user arriving at Port Authority saying "Where can I sleep tonight?" is not recognized as a shelter request. "Port Authority" is not a known location, and the long message bypasses regex. P7 fix (Port Authority as a landmark location + stricter thanks classifier) is implemented but the scenario still fails intermittently. Tracked in EVAL_RESULTS.md.

**`adversarial_fake_service` graceful handling.** A request for an impossible service (e.g., "helicopter ride") proceeds to a meaningless search rather than being redirected gracefully to real alternatives. P6 guard clause in the confirmation builder is pending.

**Phone number redaction in confirmation echo.** When a user includes a phone number in their message, the number is redacted from the stored transcript but may still appear in the bot's confirmation echo before being stored. P5 fix (run `redact_pii()` on outgoing responses) is pending.

## Documentation

| Document | Description |
|---|---|
| [FEATURES.md](FEATURES.md) | Full feature reference — conversation & intake, crisis detection, search & results, service cards, privacy & safety, staff tools |
| [CRISIS_DETECTION.md](CRISIS_DETECTION.md) | Crisis detection — two-stage architecture, category definitions, fail-open policy, phrase list design, LLM prompt, and how to extend |
| [METRICS.md](METRICS.md) | Success metrics — 18 metrics across 5 layers with definitions, targets, measurement methods, and pilot vs. post-pilot phasing |
| [EVAL_RESULTS.md](EVAL_RESULTS.md) | Eval history — per-scenario scores, critical failures, and fixes across all 7 runs |
| [SETUP.md](SETUP.md) | Local development setup — virtual environment, dependencies, API keys, running locally |
| [DEPLOY.md](DEPLOY.md) | Render deployment — environment variables, build commands, auto-deploy, free tier notes |
| [TESTING.md](TESTING.md) | Test suite guide — 444 unit tests across 14 suites + 83-scenario LLM-as-judge evaluation framework |
| [scripts/DB_AUDIT.md](scripts/DB_AUDIT.md) | Database audit script — why it exists, how to run it, when to run it, and how to interpret results |

## Related Repositories

| Repo | Description |
|---|---|
| [streetlives/yourpeer.nyc](https://github.com/streetlives/yourpeer.nyc) | The YourPeer web application (Next.js) |
| [streetlives/chat-poc](https://github.com/streetlives/chat-poc) | Original chat proof-of-concept with database schema exploration |

## License

Copyright © 2026 Streetlives, Inc.
