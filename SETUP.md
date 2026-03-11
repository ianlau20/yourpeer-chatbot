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
Currently runs a chatbot that simply tells you what you said back to you.
Below are the instructions if you want to test it out.

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
  "response": "You said: dev ian is the best"
}

The current flow:
User → POST /chat → Backend → chatbot.py → Response
The goal flow:
User → Backend → LLM → query templates → Streetlives data