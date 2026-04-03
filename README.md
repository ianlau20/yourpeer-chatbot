# YourPeer Chatbot

A conversational interface that helps people experiencing homelessness find free services in New York City — food, shelter, clothing, showers, health care, legal help, and more.

Built by [Streetlives](https://www.streetlives.nyc/) as a front-end to the [YourPeer](https://yourpeer.nyc/) service directory.

## How It Works

A user describes what they need in plain language. The chatbot extracts the service type and location through natural conversation, then queries the Streetlives database and returns real, verified service listings as interactive cards — with addresses, hours, phone numbers, and links to the full YourPeer listing.

```
User:  "I need food in Brooklyn"
Bot:   extracts → service_type=food, location=Brooklyn
       queries → Streetlives DB (2,400+ locations, 3,500+ services)
       returns → service cards with names, addresses, hours, and action buttons
```

**No hallucination by design.** The LLM handles conversation only — all service data comes from deterministic database queries using pre-reviewed templates. The bot never makes up service names, addresses, or eligibility rules.

## Architecture

```
User → Chat UI → FastAPI → Message Classifier → Slot Extraction → Query Templates → Streetlives DB
                                 ↓                     ↓                                    ↓
                          Crisis Detection        PII Redaction                       Service Cards
                          Greeting / Reset             ↓                                    ↓
                          Thanks / Help          Session Store                      YourPeer links
                          Escalation                   ↓
                                ↓                Gemini LLM (fallback
                         Static responses +      for general conversation
                         crisis resources        and DB failures only)
```

The system follows a **Safer, Limited RAG** pattern with three phases:

1. **Intake** — Slot extraction collects structured fields (service type, location, age, urgency, gender) through multi-turn conversation. Uses regex by default; when `ANTHROPIC_API_KEY` is set, a tiered approach runs regex first and calls Claude for ambiguous inputs. The message classifier routes crisis language, greetings, resets, escalation requests, and help before slot extraction runs. PII is redacted from stored transcripts.
2. **Query** — Pre-defined, parameterized SQL templates run against the Streetlives PostgreSQL database. Borough-level queries expand to include all neighborhood city values. If the strict query returns no results, filters are automatically relaxed while keeping location boundaries.
3. **Rendering** — Results are returned as structured service cards with open/closed status, never as LLM-generated text. The LLM is only used for general conversational messages and as a fallback when the database is unreachable.

## Features

- **9 service categories** — food, shelter, clothing, personal care, health care, mental health, legal, employment, and other services (benefits, IDs, etc.)
- **Conversational slot-filling** — multi-turn dialog that asks only what's needed, one question at a time
- **LLM-enhanced extraction** — optional Claude-powered slot extraction handles nuanced inputs like "my son is 12 and needs a coat" or "I'm in Queens but looking for food in the Bronx." Activates automatically when `ANTHROPIC_API_KEY` is set; falls back to regex-only otherwise
- **Crisis detection** — detects suicide/self-harm, violence, domestic violence, trafficking, and medical emergency language and immediately surfaces category-specific resources (988 Lifeline, Trevor Project, National DV Hotline, Trafficking Hotline, 911)
- **Escalation to peer navigators** — "connect with peer navigator" or "talk to a person" routes to human support contact info
- **Service cards with actions** — call, get directions, visit website, or learn more on YourPeer
- **Open/closed status** — real-time hours from the database displayed on each card
- **PII redaction** — names, phone numbers, SSNs, emails, and addresses are scrubbed from stored transcripts before storage
- **Borough-level search** — "shelter in Queens" searches across all Queens neighborhoods (Astoria, Flushing, Jamaica, etc.), not just entries with `city = "Queens"`
- **Near-me handling** — detects "food near me" and asks for a real neighborhood instead of failing
- **Location normalization** — maps boroughs and 30+ NYC neighborhoods to database-compatible values
- **Relaxed fallback** — if strict filters return no results, automatically broadens the search while keeping location boundaries
- **Conversational routing** — greetings, thanks, help requests, and "start over" are handled naturally without triggering database queries
- **Graceful degradation** — if the database is unreachable, falls back to LLM; if LLM also fails, returns a safe static message

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Slot Extraction | Regex (default) + Claude Sonnet via Anthropic API (optional, for nuanced inputs) |
| Conversational Fallback | Google Gemini (dialog only, not for service data) |
| Database | Streetlives PostgreSQL on AWS RDS (read-only) |
| Frontend | Vanilla HTML/CSS/JS with service card carousel |
| Deployment | Render (free tier) |

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
# Edit .env with your GEMINI_API_KEY and DATABASE_URL
# Optional: add ANTHROPIC_API_KEY for LLM-enhanced slot extraction

# Run
cd backend
uvicorn app.main:app --reload

# Open http://127.0.0.1:8000
```

See [SETUP.md](SETUP.md) for detailed instructions including IDE configuration and troubleshooting.

## Documentation

| Document | Description |
|---|---|
| [SETUP.md](SETUP.md) | Local development setup — virtual environment, dependencies, API keys, running locally |
| [DEPLOY.md](DEPLOY.md) | Render deployment — environment variables, build commands, auto-deploy, free tier notes |
| [TESTING.md](TESTING.md) | Test suite guide — 221 tests across 8 suites, how to run, what's covered, how to add tests |

## Related Repositories

| Repo | Description |
|---|---|
| [streetlives/yourpeer.nyc](https://github.com/streetlives/yourpeer.nyc) | The YourPeer web application (Next.js) |
| [streetlives/chat-poc](https://github.com/streetlives/chat-poc) | Original chat proof-of-concept with database schema exploration |

## License

Copyright © 2026 Streetlives, Inc.
