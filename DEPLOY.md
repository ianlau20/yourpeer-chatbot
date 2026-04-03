# Deployment Guide

## Platform: Render (Free Tier)

The app deploys as a single Render web service. FastAPI serves both the API and the frontend static files, so no separate static site is needed.

### Prerequisites

- All changes pushed to GitHub
- A [Render](https://render.com) account (sign up with GitHub)
- Your `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)
- Your `DATABASE_URL` in the format: `postgresql://user:password@host:port/streetlives`
- Your `ANTHROPIC_API_KEY` from [Anthropic Console](https://console.anthropic.com/) (optional but recommended — enables LLM-enhanced slot extraction)

### Files required

These files must be in your repo before deploying:

- `render.yaml` in the repo root (tells Render how to build and start)
- `backend/app/main.py` updated to serve frontend static files and error pages
- `frontend/app.js` with `API_URL` set to `"/chat/"` (relative, not localhost)
- `frontend/404.html` and `frontend/500.html` for error pages

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
   - `ANTHROPIC_API_KEY` = your Anthropic API key (optional — enables LLM slot extraction)
7. Click **Create Web Service**

The build takes 2–3 minutes. When it finishes, your app will be live at a URL like `https://yourpeer-chatbot.onrender.com`.

### After deploy

- The chat interface loads at the root URL (`/`)
- The staff review console is at `/admin/`
- The API is at `/chat/`
- API health check is at `/api/health`
- FastAPI docs are at `/docs`
- Unknown URLs show a styled 404 page
- Server errors show a styled 500 page with crisis numbers

### Auto-deploy

Render automatically redeploys when you push to the `main` branch. No manual action needed after the initial setup.

### Free tier limitations

- The service spins down after 15 minutes of inactivity
- First request after idle takes ~30 seconds (cold start)
- Warm up the URL a minute before any demo by visiting it in your browser
- The audit log (staff console data) is in-memory and resets on each deploy or spin-down
- For always-on hosting, upgrade to Render's Starter tier ($7/month)

### Environment variables reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key for LLM dialog |
| `GEMINI_MODEL` | Yes | Model name (use `gemini-3-flash-preview`) |
| `DATABASE_URL` | Yes | PostgreSQL connection string for Streetlives DB |
| `ANTHROPIC_API_KEY` | No | Anthropic API key. Enables LLM-enhanced slot extraction for nuanced inputs and the LLM-as-judge evaluation. Without this, the system falls back to regex-only slot extraction (still functional, less accurate on complex inputs) |

### Outbound IPs

If the Streetlives database has an IP allowlist, you'll need to add your Render service's outbound IPs. Find them in the Render Dashboard: open your service → click **Connect** (upper right) → switch to the **Outbound** tab → copy the IP ranges and add them to the database's security group or access rules.

### Troubleshooting

**Build fails with missing module:** Make sure `requirements.txt` includes `sqlalchemy`, `psycopg2-binary`, and `anthropic`.

**Frontend not loading:** Confirm that the `frontend/` folder exists at the repo root alongside `backend/`. The updated `main.py` looks for it at `../frontend/` relative to the backend.

**Database connection errors:** Verify the `DATABASE_URL` is correct in the Render dashboard under Environment Variables. The staging DB host is `streetlives-stag.cd1mqmjnwg1v.us-east-1.rds.amazonaws.com`.

**LLM slot extraction not working:** Check that `ANTHROPIC_API_KEY` is set in the Render dashboard. The app logs whether LLM extraction is enabled on startup. Without the key, everything still works — it just uses regex-only extraction.

**Staff console empty after deploy:** The audit log is in-memory and starts empty on each deploy. Data populates as users chat. For persistent audit data, replace the in-memory store with a database.

**CORS errors in browser console:** The updated `main.py` uses `allow_origins=["*"]` for demo purposes. This should be tightened for production.
