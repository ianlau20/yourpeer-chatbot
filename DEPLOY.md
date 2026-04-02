# Deployment Guide

## Platform: Render (Free Tier)

The app deploys as a single Render web service. FastAPI serves both the API and the frontend static files, so no separate static site is needed.

### Prerequisites

- All changes pushed to GitHub
- A [Render](https://render.com) account (sign up with GitHub)
- Your `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)
- Your `DATABASE_URL` in the format: `postgresql://user:password@host:port/streetlives`

### Files required

These files must be in your repo before deploying:

- `render.yaml` in the repo root (tells Render how to build and start)
- `backend/app/main.py` updated to serve frontend static files
- `frontend/app.js` with `API_URL` set to `"/chat/"` (relative, not localhost)

### Deploy steps

1. Go to [render.com](https://render.com) and sign in with GitHub
2. Click **New → Web Service**
3. Connect the `ianlau20/yourpeer-chatbot` repository
4. Render should auto-detect the `render.yaml`. If not, configure manually:
   - **Root Directory:** `backend`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Select the **Free** instance type
6. Under **Environment Variables**, add:
   - `GEMINI_API_KEY` = your Google AI Studio key
   - `GEMINI_MODEL` = `gemini-3-flash-preview`
   - `DATABASE_URL` = your full PostgreSQL connection string
7. Click **Create Web Service**

The build takes 2–3 minutes. When it finishes, your app will be live at a URL like `https://yourpeer-chatbot.onrender.com`.

### After deploy

- The frontend loads at the root URL (`/`)
- The API is at `/chat/`
- API health check is at `/api/health`
- FastAPI docs are at `/docs`

### Auto-deploy

Render automatically redeploys when you push to the `main` branch. No manual action needed after the initial setup.

### Free tier limitations

- The service spins down after 15 minutes of inactivity
- First request after idle takes ~30 seconds (cold start)
- Warm up the URL a minute before any demo by visiting it in your browser
- For always-on hosting, upgrade to Render's Starter tier ($7/month)

### Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key for LLM dialog |
| `GEMINI_MODEL` | Yes | Model name (use `gemini-3-flash-preview`) |
| `DATABASE_URL` | Yes | PostgreSQL connection string for Streetlives DB |

### Troubleshooting

**Build fails with missing module:** Make sure `requirements.txt` includes `sqlalchemy` and `psycopg2-binary`.

**Frontend not loading:** Confirm that the `frontend/` folder exists at the repo root alongside `backend/`. The updated `main.py` looks for it at `../frontend/` relative to the backend.

**Database connection errors:** Verify the `DATABASE_URL` is correct in the Render dashboard under Environment Variables. The staging DB host is `streetlives-stag.cd1mqmjnwg1v.us-east-1.rds.amazonaws.com`.

**CORS errors in browser console:** The updated `main.py` uses `allow_origins=["*"]` for demo purposes. This should be tightened for production.
