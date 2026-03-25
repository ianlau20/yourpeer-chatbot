# Setup Guide

## Backend

### 1. Create virtual environment

```bash
python3 -m venv backend/venv
```

### 2. Activate virtual environment and install dependencies

**Windows:**
```powershell
backend\venv\Scripts\activate
```

**Mac/Linux:**
```bash
source backend/venv/bin/activate
```

**Then install:**
```bash
pip install -r backend/requirements.txt
```

### 3. IDE setup (Cursor / VS Code)

**Mac/Linux users:** The workspace is configured for Windows. Select the correct interpreter:

1. Open Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`)
2. Run **Python: Select Interpreter**
3. Choose the interpreter from `backend/venv`

### 4. Run the backend

From the repo root with venv activated:

```bash
cd backend
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

## Frontend (demo UI)

A minimal static chat page lives in `frontend/` (`index.html`, `styles.css`, `app.js`). It calls `POST http://127.0.0.1:8000/chat/`. The backend enables **CORS** for common local origins on port **5500** so the browser can call the API.

On load, the page shows a short **welcome message**. The demo keeps a **`session_id`** (in browser storage) so multi-turn chats reuse the same conversation and slot state on the backend. Bot replies strip common Markdown-style `*` / `**` markers for plain-text display.

**Run the demo (use a second terminal; keep the backend running):**

From the repo root:

```bash
cd frontend
python3 -m http.server 5500 --bind 127.0.0.1
```

Then open **http://127.0.0.1:5500** in your browser (avoid `http://[::1]:5500` unless your backend CORS list includes that origin).

**Stop / restart the frontend server:** in that terminal, press `Ctrl+C`, then run the `http.server` command again.

### Testing
This backend uses the Gemini LLM. To test it, co-developers must set a `GEMINI_API_KEY` and use `GEMINI_MODEL=gemini-3-flash-preview`.

Before starting the backend, create/update your `.env` file (repo root is recommended):

```
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3-flash-preview"
```

To try the chat locally:

1. Start the backend (`uvicorn` in `backend/`).
2. Start the frontend static server (commands above).
3. Open http://127.0.0.1:5500 — you should see the welcome line, then type a message and click **Send**.

The current flow:
User → demo page → slot extraction + session merge → (follow-up or Gemini) → Response

The goal flow:
User → Backend → LLM + query templates → Streetlives data