# Deployment Guide

## Platform: Render

The app deploys as **two Render services** from a single repo:

| Service | Type | Root dir | What it runs |
|---------|------|----------|-------------|
| `yourpeer-chatbot-api` | Python | `backend/` | FastAPI — headless API |
| `yourpeer-chatbot` | Node | `frontend-next/` | Next.js — chat UI + admin console |

The Next.js frontend proxies API calls to the FastAPI backend via `rewrites` in `next.config.js`.

### Prerequisites

- All changes pushed to GitHub
- A [Render](https://render.com) account (sign up with GitHub)
- Node.js 18.18+ (Render handles this via the `nodeVersion` in `render.yaml`)
- Your `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey)
- Your `DATABASE_URL` in the format: `postgresql://user:password@host:port/streetlives`
- Your `ANTHROPIC_API_KEY` from [Anthropic Console](https://console.anthropic.com/) (optional but recommended — enables LLM-enhanced slot extraction)

### Files required

These files must be in your repo before deploying:

- `render.yaml` in the repo root (defines both services)
- `backend/app/main.py` as a headless API (no static file serving)
- `frontend-next/` directory with `package.json`, `next.config.js`, and all source files
- `frontend-next/src/lib/chat/` directory with `types.ts`, `api.ts`, `store.ts`

### Deploy steps

1. Go to [render.com](https://render.com) and sign in with GitHub
2. Click **New → Blueprint**
3. Connect the `ianlau20/yourpeer-chatbot` repository and select the `frontend` branch
4. Render reads `render.yaml` and creates both services automatically
5. On the **backend service** (`yourpeer-chatbot-api`), set the secret environment variables:
   - `GEMINI_API_KEY` = your Google AI Studio key
   - `DATABASE_URL` = your full PostgreSQL connection string
   - `ANTHROPIC_API_KEY` = your Anthropic API key (optional)
6. On the **frontend service** (`yourpeer-chatbot`), verify that `CHAT_BACKEND_URL` is set to the backend's Render URL (e.g. `https://yourpeer-chatbot-api.onrender.com`). Update it if the auto-generated name differs.
7. Deploy both services

The backend build takes 2–3 minutes. The frontend build takes 1–2 minutes. When both finish, your app will be live.

### After deploy

- The chat interface is at `https://yourpeer-chatbot.onrender.com/chat`
- The staff review console is at `https://yourpeer-chatbot.onrender.com/admin`
- The API health check is at `https://yourpeer-chatbot-api.onrender.com/api/health`
- FastAPI docs are at `https://yourpeer-chatbot-api.onrender.com/docs`

### Auto-deploy

Render automatically redeploys both services when you push to the branch configured in the Blueprint. No manual action needed after initial setup.

### Free tier limitations

- Both services spin down after 15 minutes of inactivity
- First request after idle takes ~30 seconds per service (cold start). The frontend wakes first, then its first API call wakes the backend — so expect ~60 seconds total on first visit after idle.
- Warm up both URLs a minute before any demo by visiting each in your browser
- The audit log (staff console data) is in-memory and resets on each deploy or spin-down
- For always-on hosting, upgrade both services to Render's Starter tier ($7/month each)

### Environment variables reference

#### Backend service (`yourpeer-chatbot-api`)

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key for LLM dialog |
| `GEMINI_MODEL` | Yes | Model name (use `gemini-3-flash-preview`) — set automatically by `render.yaml` |
| `DATABASE_URL` | Yes | PostgreSQL connection string for Streetlives DB |
| `ANTHROPIC_API_KEY` | No | Enables LLM-enhanced slot extraction and the LLM-as-judge evaluation suite. Without this, the system falls back to regex-only slot extraction (still functional, less accurate on complex inputs) |

#### Frontend service (`yourpeer-chatbot`)

| Variable | Required | Description |
|---|---|---|
| `CHAT_BACKEND_URL` | Yes | Full URL of the backend service (e.g. `https://yourpeer-chatbot-api.onrender.com`) — set automatically by `render.yaml` |
| `PORT` | Yes | Port for Next.js to listen on — set automatically by `render.yaml` to `3000` |

### Outbound IPs

If the Streetlives database has an IP allowlist, you'll need to add your **backend** service's outbound IPs. Find them in the Render Dashboard: open the `yourpeer-chatbot-api` service → click **Connect** (upper right) → switch to the **Outbound** tab → copy the IP ranges and add them to the database's security group or access rules.

The frontend service does not connect to the database directly.

### Troubleshooting

**Backend build fails with missing module:** Make sure `backend/requirements.txt` includes `sqlalchemy`, `psycopg2-binary`, and `anthropic`.

**Frontend build fails with Node version error:** The `render.yaml` specifies `nodeVersion: "24"`. If you see syntax errors like `Unexpected token '??='`, Render may be using an older Node. Check the Render dashboard to confirm the Node version matches.

**Frontend build fails with missing modules:** Run `cd frontend-next && rm package-lock.json && npm install` locally, commit the regenerated `package-lock.json`, and push.

**Chat page loads but no responses:** Check that `CHAT_BACKEND_URL` on the frontend service points to the correct backend URL. Open the backend URL directly in your browser — you should see `{"message": "YourPeer chatbot API is running. Frontend served by Next.js."}`.

**Database connection errors:** Verify the `DATABASE_URL` is correct in the Render dashboard under the backend service's Environment Variables.

**LLM slot extraction not working:** Check that `ANTHROPIC_API_KEY` is set on the backend service. The app logs whether LLM extraction is enabled on startup. Without the key, everything still works — it just uses regex-only extraction.

**Staff console empty after deploy:** The audit log is in-memory and starts empty on each deploy. Data populates as users chat. For persistent audit data, replace the in-memory store with a database.

**CORS errors in browser console:** The backend uses `allow_origins=["*"]` for demo purposes. For production, restrict this to the frontend's domain.

**Cold start timeout:** On the free tier, if the backend hasn't been accessed in 15 minutes, the first frontend request may time out waiting for the backend to wake. Visit the backend's health endpoint (`/api/health`) first to warm it up, then load the frontend.
