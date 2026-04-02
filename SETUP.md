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

### 4. Run the backend

From the repo root with venv activated:

```
cd backend
uvicorn app.main:app --reload
```

The app (API + frontend) will be available at `http://127.0.0.1:8000`.

## Frontend

The chat UI lives in `frontend/` (`index.html`, `styles.css`, `app.js`). The backend serves these files directly — no separate frontend server is needed. Just start the backend and open `http://127.0.0.1:8000` in your browser.

On load, the page shows a welcome message with a privacy disclosure. The demo keeps a **`session_id`** so multi-turn chats reuse the same conversation and slot state on the backend. When the bot finds matching services, they render as swipeable cards with address, phone, hours, and action buttons.

### Environment variables

To get a Gemini API key, go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey), sign in with a Google account, and click "Create API key." The free tier is sufficient for development.

Before starting the backend, create/update your `.env` file (repo root is recommended):

```
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3-flash-preview"
DATABASE_URL="postgresql://user:password@host:port/streetlives"
```

### Testing locally

1. Activate the virtual environment.
2. Start the backend: `cd backend && uvicorn app.main:app --reload`
3. Open <http://127.0.0.1:8000> — you should see the welcome message, then type something like "I need food in Brooklyn" and click Send.

### Useful endpoints

- `http://127.0.0.1:8000` — Chat UI
- `http://127.0.0.1:8000/docs` — FastAPI interactive API docs
- `http://127.0.0.1:8000/api/health` — Health check

### Architecture

User → Chat UI → FastAPI → Slot extraction → Query templates → Streetlives DB → Service cards

For deployment instructions, see [DEPLOY.md](DEPLOY.md).
