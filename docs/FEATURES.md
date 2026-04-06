# Features

Full feature reference for the YourPeer chatbot. For setup and architecture see [README.md](../README.md).

---

## Conversation & Intake

See [CHATBOT_BEHAVIOR.md](CHATBOT_BEHAVIOR.md) for the full routing pipeline, guardrails, and how to extend.

- **9 service categories** — food, shelter, clothing, personal care, health care, mental health, legal, employment, and other services (benefits, IDs, etc.)
- **Quick-reply buttons** — tappable category buttons on welcome (Food, Shelter, Showers, Clothing, etc.), borough buttons when location is needed, and confirmation actions — no typing required
- **Confirmation before search** — bot summarizes what it will search for and lets the user confirm, change location, change service, or start over before querying the database
- **Conversational slot-filling** — multi-turn dialog that asks only what's needed, one question at a time
- **LLM-enhanced extraction** — optional Claude Sonnet slot extraction handles nuanced inputs like "my son is 12 and needs a coat" or "I'm in Queens but looking for food in the Bronx." Uses a complexity-based routing strategy: regex for simple messages, LLM for complex ones. Activates automatically when `ANTHROPIC_API_KEY` is set; falls back to regex-only otherwise
- **Conversational routing** — greetings, thanks, help requests, "start over", and other common patterns are handled naturally without triggering database queries
- **Frustration handling** — detects expressions like "that wasn't helpful" or "I already tried those places" and responds with empathy plus escalation options instead of another search attempt
- **Bot identity transparency** — "are you a robot?" or "am I talking to a person?" triggers an honest AI disclosure with an offer to connect to a real person
- **Overwhelm/confusion routing** — "I don't know what to do" or "I'm lost" shows gentle guidance with category buttons instead of sending the message to the LLM (which would misinterpret it as a mental health request)
- **Escalation to peer navigators** — "connect with peer navigator" or "talk to a person" routes to human support contact info

---

## Crisis Detection

- **Two-stage crisis detection** — regex pre-check (<1ms) followed by Claude Sonnet LLM classification (1–3s, only when regex misses). Catches direct and indirect crisis language that can't be fully enumerated in a keyword list
- **Six crisis categories** — suicide/self-harm (including passive ideation like "what's the point anymore"), domestic violence, safety concerns (runaway, unsafe home, being kicked out), trafficking, medical emergencies, and threats of violence
- **Category-specific resources** — each category surfaces its own set of hotlines: 988 Lifeline, Crisis Text Line, Trevor Project, National DV Hotline, NYC DV Hotline, Safe Horizon, National Trafficking Hotline, Poison Control, 911
- **Passive ideation detection** — indirect hopelessness phrases ("nothing helps anymore", "better off without me", "can't keep going") are included in the suicide/self-harm category
- **Youth runaway detection** — "ran away from home", "kicked out of my home", "can't go home" trigger safety concern resources alongside any shelter search
- **Fail-open LLM policy** — if the LLM is unavailable when invoked, returns a general safety response rather than falling through to normal conversation. Only applies to messages that reached the LLM stage (ambiguous messages where regex didn't fire)
- **Non-disruptive** — crisis response does not clear the session; the user can continue their service search afterwards

See [CRISIS_DETECTION.md](CRISIS_DETECTION.md) for architecture, phrase list design, and how to extend.

---

## Search & Results

- **Borough-level search** — uses `pa.borough` column directly (not city name expansion), which is clean and consistent across all five boroughs including Staten Island
- **Neighborhood proximity search** — PostGIS `ST_DWithin` with 59 neighborhood center coordinates returns genuinely local results; falls back to full-borough on no results
- **Near-me handling** — detects "food near me" and offers browser geolocation ("Use my location") alongside borough buttons; falls back to asking for a neighborhood if geolocation is denied
- **Geolocation error specificity** — when location access fails, the user sees a specific reason ("Location access was denied" / "Your device couldn't determine your location" / "The location request timed out") instead of a generic error, with borough buttons as fallback
- **Unrecognized service redirect** — when a user requests something the bot can't help with (e.g., "helicopter ride"), the bot acknowledges it can't help with that specifically and shows the full service menu with available categories, rather than falling through to a generic conversation response
- **Location normalization** — maps all five boroughs and 59 NYC neighborhoods to database-compatible values, including "the Bronx" → "Bronx" and "manhattan" → "Manhattan"
- **Data-informed nearby borough suggestions** — when a search returns no results, suggests the borough with the highest actual service count for that category (based on DB audit), not just the geographically closest borough. Only offered for borough-level searches, not neighborhood searches
- **Relaxed fallback** — if strict filters return no results, automatically broadens the search while keeping location boundaries
- **Graceful degradation** — if the database is unreachable, falls back to LLM; if LLM also fails, returns a safe static message

---

## Service Cards

- **No hallucination** — all service data comes from deterministic SQL query templates against the Streetlives database. The LLM never generates service names, addresses, hours, or phone numbers
- **Service cards with actions** — call, get directions, visit website, or learn more on YourPeer
- **Open/closed status** — hours from the database displayed on each card where available; "Call for hours" shown when schedule data is absent (most categories have sparse schedule coverage)
- **Referral badge** — cards show "Referral may be required" for the 624 services in the database that have membership requirements, rather than silently filtering them out
- **URL normalization** — website links from the database are normalized to include `https://` so they open correctly in all browsers

---

## Privacy & Safety

- **PII redaction** — names, phone numbers, SSNs, emails, and addresses are scrubbed from stored transcripts before storage
- **No session linkage** — sessions use anonymous `conversation_id` values with ephemeral keys; no cookies or device IDs beyond necessary rate limiting
- **Anonymized audit log** — every conversation turn, database query, crisis detection, and session reset is recorded in a thread-safe in-memory ring buffer (capped at 2,000 events). No PII is stored
- **Local storage caveat** — chat history is persisted in the browser's `localStorage` to survive page refreshes. This includes the user's raw messages (PII redaction only happens server-side). Data auto-expires after 30 minutes of inactivity and is cleared immediately when the user taps "start over." On shared or public devices, stored data is theoretically accessible via browser developer tools until it expires

---

## Security

- **CORS allowlist** — only configured origins can make cross-origin requests; controlled via `CORS_ALLOWED_ORIGINS` env var
- **CSRF middleware** — validates `Origin` and `Referer` headers on state-changing requests from browsers
- **HMAC-signed session tokens** — session IDs are signed with `SESSION_SECRET` so clients cannot forge or tamper with them
- **Admin API key auth** — all `/admin/api/*` endpoints require `Authorization: Bearer <ADMIN_API_KEY>` when the key is configured; open in dev mode when unset
- **CSP headers** — Content-Security-Policy, X-Frame-Options, X-Content-Type-Options, and Permissions-Policy headers set via Next.js config
- **Eval subprocess isolation** — eval runs execute in a separate subprocess to prevent blocking the web server

---

## Stability & Rate Limiting

- **Message length limit** — chat messages are capped at 10,000 characters via Pydantic validation; oversized messages get a 422 response before any processing
- **LLM timeout** — all Anthropic API calls time out after 10 seconds
- **DB statement timeout** — PostgreSQL queries are capped at 5 seconds via `statement_timeout`
- **Frontend fetch timeout** — all `fetch()` calls use `AbortSignal.timeout()` — 30 seconds for chat, 15 seconds for admin/feedback
- **Chat rate limits** — per-session (12/min, 60/hr, 200/day) and per-IP (60/min, 300/hr) sliding-window limits; configurable via env vars
- **Admin rate limits** — per-IP (120/min, 600/hr) for all admin endpoints; stricter limit (5/hr) for eval runs which consume LLM API credits
- **Feedback rate limit** — 10 requests per session per minute
- **Rate limiter memory management** — 10-minute entry TTL, 1-minute eviction sweep, hard cap of 5,000 tracked keys with forced eviction above the cap
- **Session eviction** — in-memory session store uses LRU eviction at 500-session cap; 30-minute TTL per session

---

## Frontend State Management

- **Chat history persistence** — conversation state (messages, session ID) is synced to `localStorage` via Zustand `persist` middleware. Users keep their conversation across page refreshes and tab close/reopen. Auto-resets after 30 minutes of inactivity to match the backend session TTL
- **Shared device privacy note** — localStorage stores the user's raw messages (PII redaction only runs on the backend). On shared or public computers, the next user could inspect stored data via browser developer tools. The 30-minute auto-expire and "start over" (which clears localStorage immediately) mitigate this, but users on shared devices should be aware that their conversation is stored locally until it expires. A future improvement could add an explicit "clear history" option or a notice on first visit
- **Admin data caching** — all admin pages share a centralized Zustand store with staleness-based caching (30-second threshold). Navigating between admin tabs reuses cached data instead of re-fetching from the API on every navigation
- **Offline detection** — a `useOnlineStatus` hook tracks `navigator.onLine` and listens for browser `online`/`offline` events. When the user goes offline, an amber banner appears below the chat ("You appear to be offline") and the input field is disabled to prevent sending messages that would fail with cryptic errors
- **Retry on failed API calls** — when a chat message fails (after one automatic retry with 1.5-second backoff for transient errors), the error message includes a "Retry" button that re-sends the original message. Rate-limit errors (429) and auth errors (403) are not auto-retried since they require different handling. Clicking Retry removes the error message and re-submits the original text

---

## Accessibility

The frontend is designed for the population served — people who may be using screen readers, keyboard-only navigation, or voice input on shared or low-end devices.

- **Screen reader support** — chat messages are announced via `aria-live` regions as they arrive. User and bot messages are labeled distinctly ("You said" / "YourPeer said"). Loading and error states are announced without interrupting the conversation flow
- **Keyboard navigation** — every interactive element is reachable and operable via keyboard. The service carousel supports left/right arrow keys. Admin conversation rows respond to Enter and Space. Focus management returns to the input after sending
- **Voice input** — Web Speech API microphone button for users who prefer speaking to typing. Interim transcripts appear in real time. The button auto-hides on browsers without speech support, and shows clear error messages for denied mic access
- **Semantic HTML** — the chat area uses `role="log"`, the carousel uses `role="region"` with `aria-roledescription="carousel"`, service cards use `role="listitem"` with position announcements ("result 1 of 3"), quick replies are grouped with `role="group"`
- **Labeled controls** — all icon-only buttons have `aria-label` attributes (send, mic, previous/next, thumbs up/down, close). The text input has a visually hidden `<label>`. Action links on service cards include the service name ("Call Food Pantry", "Get directions to Food Pantry")
- **Decorative elements hidden** — all decorative icons (map pin, phone, clock, mail) and carousel dot indicators are marked `aria-hidden="true"` so screen readers skip them
- **Focus indicators** — all focusable elements show visible focus rings via Tailwind's `focus:ring` utilities
- **Accessible dialog** — the admin transcript viewer uses Radix Dialog, which provides keyboard trap, Escape to close, and focus restoration out of the box

---

## Staff Tools

- **Staff review console** — data stewards can view anonymized conversation transcripts, query execution logs, crisis events, and aggregate stats at `/admin`. Includes a full transcript viewer with slot metadata and crisis flags
- **Metrics tab** — 20 live metrics across 5 layers (intake quality, answer quality, safety, system quality/eval, closed-loop) with targets and status indicators. Includes task completion rate, slot confirmation/correction rates, confirmation breakdown, data freshness rate, escalation rate, no-result rate, relaxed query rate, and more
- **User feedback** — thumbs up/down on every bot response; feedback scores are surfaced in the admin Overview and Metrics tabs
- **In-browser eval runner** — the Eval tab in the staff console includes a "Run Evals" button that triggers the LLM-as-judge suite as a FastAPI background task, with live progress polling and a scenario count selector (5 / 10 / 20 / all)
- **LLM-as-judge evaluation** — 85-scenario automated evaluation framework across 17 categories, simulating conversations and scoring across 8 quality dimensions: slot extraction accuracy, dialog efficiency, response tone, safety & crisis handling, confirmation UX, privacy protection, hallucination resistance, and error recovery. Outputs a structured report with per-scenario scores, critical failure tracking, and category averages. See [EVAL_RESULTS.md](EVAL_RESULTS.md) for full run history
- **Centralized data store** — admin pages share a Zustand store with 30-second staleness caching, eliminating redundant API calls when navigating between tabs

---

## Known Limitations

These are tracked issues identified during DB audits and pilot testing, deferred for post-pilot resolution. See [README.md — Known Limitations](../README.md#known-limitations--future-work) for detail.

- Result ordering uses open-now / recently-verified / name; proximity-first when geolocation available
- `additional_info` field is effectively empty (99.7% null)
- Schedule data is sparse for most categories — open/closed filtering intentionally disabled
- `natural_new_to_nyc` slot extraction failure (P7 pending)
- `adversarial_fake_service` graceful handling (P6 pending)
- `phone_number_redaction_in_confirmation` echo (P5 pending)
- In-memory audit log and session store reset on server restart — persistent storage deferred to post-pilot
