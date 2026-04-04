# Setup Guide

## Prerequisites

| Tool | Minimum version | Check with |
|------|----------------|------------|
| **Node.js** | 18.18+ (recommended: 24.x) | `node --version` |
| **npm** | 9+ (ships with Node 18+) | `npm --version` |
| **Python** | 3.10+ | `python3 --version` |

Next.js 15 requires Node 18.18 or later. The production yourpeer.nyc app uses Node 24.x.

**If your Node version is too old**, install or update via [nvm](https://github.com/nvm-sh/nvm):

```
nvm install 24
nvm use 24
```

Or download directly from [nodejs.org](https://nodejs.org/).

## Architecture

The app runs as **two processes** locally:

| Process | Port | What it serves |
|---------|------|----------------|
| **FastAPI backend** | `:8000` | Chat API (`/chat/`), Admin API (`/admin/api/*`), health check |
| **Next.js frontend** | `:3000` | All pages (`/chat`, `/admin/*`, existing yourpeer.nyc routes) |

Next.js proxies API calls to FastAPI via `rewrites` in `next.config.js`.

```
Browser (:3000)
  ├── /chat              → Next.js renders ChatContainer
  ├── /admin/overview    → Next.js renders admin dashboard
  ├── /api/chat          → rewrite → FastAPI :8000/chat/
  ├── /api/admin/stats   → rewrite → FastAPI :8000/admin/api/stats
  └── / (yourpeer.nyc)   → existing Next.js pages
```

## 1. Backend Setup

### Create virtual environment

```
python3 -m venv backend/venv
```

### Activate and install dependencies

**Mac/Linux:**

```
source backend/venv/bin/activate
pip install -r backend/requirements.txt
```

**Windows:**

```
backend\venv\Scripts\activate
pip install -r backend/requirements.txt
```

### Configure environment

Create a `.env` file in the repo root:

```
DATABASE_URL="postgresql://user:password@host:port/streetlives"
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3-flash-preview"
```

**Optional:** Add `ANTHROPIC_API_KEY` for Claude-powered slot extraction.

**Database URL:** Contact the Streetlives team for PostgreSQL staging credentials. The RDS instance requires IP whitelisting.

### Run the backend

```
cd backend
uvicorn app.main:app --reload
```

Verify it's running: `curl http://localhost:8000/api/health` should return `{"status": "ok"}`.

## 2. Frontend Setup

### Verify Node version

```
node --version
```

Must be 18.18 or later. If not, see [Prerequisites](#prerequisites) above.

### Install dependencies

```
cd frontend-next
npm install
```

### Configure environment

Create a `.env.local` in the `frontend-next/` directory:

```
CHAT_BACKEND_URL=http://localhost:8000
```

### Run the frontend

```
cd frontend-next
npm run dev
```

Open `http://localhost:3000`. The chat is at `/chat`, the admin console is at `/admin`.

## 3. Running Both Together

Open two terminals:

**Terminal 1 — Backend:**

```
source backend/venv/bin/activate
cd backend
uvicorn app.main:app --reload
```

**Terminal 2 — Frontend:**

```
cd frontend-next
npm run dev
```

That's it. Changes to either backend Python or frontend TypeScript will hot-reload.

## 4. Running Tests

All 221 backend tests run without external services (database and LLM calls are mocked):

```
cd tests
python test_pii_redactor.py && python test_slot_extractor.py && python test_edge_cases.py && python test_chatbot.py && python test_location_boundaries.py && python test_query_templates.py && python test_crisis_detector.py && python test_llm_slot_extractor.py
```

To run LLM integration tests against the real Claude API:

```
ANTHROPIC_API_KEY=sk-ant-... python tests/test_llm_slot_extractor.py --live
```

## IDE Setup (Cursor / VS Code)

1. Open Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
2. Run **Python: Select Interpreter**
3. Choose the interpreter from `backend/venv`

TypeScript/Next.js support works automatically via `tsconfig.json`.

## 5. Deploying to Render (Staging)

The `render.yaml` deploys two services from this single repo:

| Service | Name | Root dir | URL |
|---------|------|----------|-----|
| FastAPI backend | `yourpeer-chatbot-api` | `backend/` | `yourpeer-chatbot-api.onrender.com` |
| Next.js frontend | `yourpeer-chatbot` | `frontend-next/` | `yourpeer-chatbot.onrender.com` |

The frontend's `CHAT_BACKEND_URL` env var points at the backend's Render URL. Next.js `rewrites` in `next.config.js` proxy `/api/chat/*` and `/api/admin/*` to the backend at that URL.

**First deploy:**

1. Push the repo to GitHub
2. Go to Render → **New** → **Blueprint** → connect the repo
3. Render reads `render.yaml` and creates both services
4. Set the secret env vars (database URL, API keys) on the backend service
5. After the backend deploys, copy its `.onrender.com` URL and update `CHAT_BACKEND_URL` on the frontend service if the default name doesn't match

**After deploy:** The chat is at `https://yourpeer-chatbot.onrender.com/chat` and the admin console is at `https://yourpeer-chatbot.onrender.com/admin`.

## Repo Structure

```
yourpeer-chatbot/
├── backend/              # FastAPI backend (headless API)
│   ├── app/
│   │   ├── main.py       # pure API — no static file serving
│   │   ├── routes/       # /chat/, /admin/api/*
│   │   ├── services/     # chatbot, crisis detector, etc.
│   │   └── ...
│   └── requirements.txt
├── frontend-next/        # Next.js frontend
│   ├── src/
│   │   ├── app/          # routes: /chat, /admin/*
│   │   ├── components/   # chat/ and admin/ components
│   │   ├── hooks/        # use-chat, use-speech-recognition
│   │   └── lib/          # store, API wrappers, types
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   └── tsconfig.json
├── tests/                # Backend test suite (unchanged)
├── render.yaml           # Deploys both services
└── SETUP.md              # This file
```
