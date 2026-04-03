# Setup Guide

## Backend

### 1. Create virtual environment

```
python3 -m venv backend/venv
```

### 2. Activate virtual environment and install dependencies

**Windows:**

```
backend\venv\Scripts\activate
```

**Mac/Linux:**

```
source backend/venv/bin/activate
```

**Then install:**

```
pip install -r backend/requirements.txt
```

### 3. IDE setup (Cursor / VS Code)

**Mac/Linux users:** The workspace is configured for Windows. Select the correct interpreter:

1. Open Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
2. Run **Python: Select Interpreter**
3. Choose the interpreter from `backend/venv`

### 4. Configure environment

Create a `.env` file in the repo root:

```
# Required
DATABASE_URL="postgresql://user:password@host:port/streetlives"
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3-flash-preview"

# Optional — enables LLM-enhanced slot extraction
ANTHROPIC_API_KEY="sk-ant-your-key"
```

**Gemini API key** — used for conversational fallback when messages don't match service keywords. Get a free key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey).

**Anthropic API key** (optional) — enables Claude-powered slot extraction for nuanced inputs like "my son is 12 and needs a coat" or "I'm in Queens but looking in the Bronx." Without this key, the system uses regex-only extraction which handles most simple inputs correctly.

**Database URL** — the Streetlives PostgreSQL staging database on AWS RDS. Contact the Streetlives team for credentials. The RDS instance requires IP whitelisting.

### 5. Run the backend

From the repo root with venv activated:

```
cd backend
uvicorn app.main:app --reload
```

The API and frontend will both be available at `http://127.0.0.1:8000`.

## Frontend

The frontend is served by FastAPI as static files — no separate server needed. Just start the backend and open `http://127.0.0.1:8000`.

The chat UI lives in `frontend/` (`index.html`, `styles.css`, `app.js`). It calls `POST /chat/` on the same server. The demo keeps a `session_id` in browser storage so multi-turn chats reuse the same conversation and slot state.

## Running Tests

See [TESTING.md](TESTING.md) for the full guide. Quick start:

```
cd tests
python test_pii_redactor.py && python test_slot_extractor.py && python test_edge_cases.py && python test_chatbot.py && python test_location_boundaries.py && python test_query_templates.py && python test_crisis_detector.py && python test_llm_slot_extractor.py
```

All 221 tests run without external services (database and LLM calls are mocked).

To run LLM integration tests against the real Claude API:

```
ANTHROPIC_API_KEY=sk-ant-... python tests/test_llm_slot_extractor.py --live
```
