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
- Node.js 18.18+ (set via `NODE_VERSION` env var in `render.yaml`)
- Your `ANTHROPIC_API_KEY` from [Anthropic Console](https://console.anthropic.com/)
- Your `DATABASE_URL` in the format: `postgresql://user:password@host:port/streetlives`

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
   - `ANTHROPIC_API_KEY` = your Anthropic API key
   - `DATABASE_URL` = your full PostgreSQL connection string
   - `SESSION_SECRET` = a random string for signing session tokens (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
   - `ADMIN_API_KEY` = a random string to protect the admin API (generate the same way)
   - `CORS_ALLOWED_ORIGINS` = your frontend URL (e.g. `https://yourpeer-chatbot-gjn7.onrender.com`)
6. On the **frontend service** (`yourpeer-chatbot`), set:
   - `CHAT_BACKEND_URL` = the backend's Render URL (e.g. `https://yourpeer-chatbot-api-gjn7.onrender.com`)
   - `ADMIN_API_KEY` = same value as the backend's `ADMIN_API_KEY` (the Next.js proxy forwards this to the backend)
7. Deploy both services

The backend build takes 2–3 minutes. The frontend build takes 1–2 minutes. When both finish, your app will be live.

### After deploy

- The chat interface is at `https://yourpeer-chatbot-gjn7.onrender.com/chat`
- The staff review console is at `https://yourpeer-chatbot-gjn7.onrender.com/admin`
- The API health check is at `https://yourpeer-chatbot-api-gjn7.onrender.com/api/health`
- FastAPI docs are at `https://yourpeer-chatbot-api-gjn7.onrender.com/docs`

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
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key — powers all LLM features (conversational responses via Haiku, slot extraction via Haiku, crisis detection via Sonnet). Without this, the system falls back to regex-only slot extraction, regex-only crisis detection, and static fallback responses |
| `DATABASE_URL` | Yes | PostgreSQL connection string for Streetlives DB |
| `SESSION_SECRET` | Production | Random string for HMAC-signing session tokens. Without this, session tokens are unsigned (fine for local dev, required for production) |
| `ADMIN_API_KEY` | Production | Random string for admin API authentication. Without this, admin endpoints are open (fine for local dev, required for production) |
| `CORS_ALLOWED_ORIGINS` | Production | Comma-separated list of allowed origins (e.g. `https://yourpeer-chatbot-gjn7.onrender.com`). Defaults to `http://localhost:3000,http://127.0.0.1:3000` for local dev |
| `PYTHON_VERSION` | No | Python version (e.g. `3.12.0`) — set automatically by `render.yaml`. Render uses its default if not set |

#### Frontend service (`yourpeer-chatbot`)

| Variable | Required | Description |
|---|---|---|
| `CHAT_BACKEND_URL` | Yes | Full URL of the backend service (e.g. `https://yourpeer-chatbot-api-gjn7.onrender.com`) — set automatically by `render.yaml` |
| `ADMIN_API_KEY` | Production | Must match the backend's `ADMIN_API_KEY`. The Next.js admin proxy forwards this as a Bearer token to the backend |
| `NODE_VERSION` | No | Node.js version (e.g. `24.0.0`) — set automatically by `render.yaml`. Render uses its default if not set |

### Outbound IPs

If the Streetlives database has an IP allowlist, you'll need to add your **backend** service's outbound IPs. Find them in the Render Dashboard: open the `yourpeer-chatbot-api` service → click **Connect** (upper right) → switch to the **Outbound** tab → copy the IP ranges and add them to the database's security group or access rules.

The frontend service does not connect to the database directly.

### Troubleshooting

**Backend build fails with missing module:** Make sure `backend/requirements.txt` includes `sqlalchemy`, `psycopg2-binary`, and `anthropic`.

**Frontend build fails with Node version error:** The `render.yaml` sets `NODE_VERSION` to `24.0.0`. If you see syntax errors like `Unexpected token '??='`, Render may be using an older Node. Check the `NODE_VERSION` env var in the Render dashboard.

**Frontend build fails with missing modules:** Run `cd frontend-next && rm package-lock.json && npm install` locally, commit the regenerated `package-lock.json`, and push.

**Chat page loads but no responses:** Check that `CHAT_BACKEND_URL` on the frontend service points to the correct backend URL. Open the backend URL directly in your browser — you should see `{"message": "YourPeer chatbot API is running. Frontend served by Next.js."}`.

**Database connection errors:** Verify the `DATABASE_URL` is correct in the Render dashboard under the backend service's Environment Variables.

**LLM slot extraction not working:** Check that `ANTHROPIC_API_KEY` is set on the backend service. The app logs whether LLM extraction is enabled on startup. Without the key, everything still works — it just uses regex-only extraction.

**Staff console empty after deploy:** The audit log is in-memory and starts empty on each deploy. Data populates as users chat. For persistent audit data, replace the in-memory store with a database.

**CORS errors in browser console:** The backend uses `allow_origins=["*"]` for demo purposes. For production, restrict this to the frontend's domain.

**Cold start timeout:** On the free tier, if the backend hasn't been accessed in 15 minutes, the first frontend request may time out waiting for the backend to wake. Visit the backend's health endpoint (`/api/health`) first to warm it up, then load the frontend.
