# Setup Guide

## Backend

### 1. Create virtual environment

```bash
python -m venv backend/venv
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

### Testing
This backend uses the Gemini LLM. To test it, co-developers must set a `GEMINI_API_KEY` and use `GEMINI_MODEL=gemini-3-flash-preview`.
Below are the instructions if you want to test it out.

Before starting the server, create/update your `.env` file (repo root is recommended):
```
GEMINI_API_KEY="your-gemini-api-key"
GEMINI_MODEL="gemini-3-flash-preview"
```

1. Open: http://127.0.0.1:8000/docs
2. Click POST /chat/
3. Click Try it out
4. You should see a JSON box, replace its contents with:
{
  "message": "dev ian is the best"
}
5. Click Execute

Then lower on the page, FastAPI should show the response.
You should get something like:
{
  "response": "<Gemini-generated text>"
}

The current flow:
User → POST /chat → Backend → chatbot.py → Response
The goal flow:
User → Backend → LLM → query templates → Streetlives data