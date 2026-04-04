# Features

Full feature reference for the YourPeer chatbot. For setup and architecture see [README.md](README.md).

---

## Conversation & Intake

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

- **Two-stage crisis detection** — regex pre-check (<1ms) followed by Claude Haiku LLM classification (1–3s, only when regex misses). Catches direct and indirect crisis language that can't be fully enumerated in a keyword list
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
- **Near-me handling** — detects "food near me" and asks for a real neighborhood instead of failing
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
- **Metrics tab** — 18 live metrics across 5 layers (intake quality, answer quality, safety, system quality/eval, closed-loop) with targets and status indicators
- **User feedback** — thumbs up/down on every bot response; feedback scores are surfaced in the admin Overview and Metrics tabs
- **In-browser eval runner** — the Eval tab in the staff console includes a "Run Evals" button that triggers the LLM-as-judge suite as a FastAPI background task, with live progress polling and a scenario count selector (5 / 10 / 20 / all)
- **LLM-as-judge evaluation** — 85-scenario automated evaluation framework across 17 categories, simulating conversations and scoring across 8 quality dimensions: slot extraction accuracy, dialog efficiency, response tone, safety & crisis handling, confirmation UX, privacy protection, hallucination resistance, and error recovery. Outputs a structured report with per-scenario scores, critical failure tracking, and category averages. See [EVAL_RESULTS.md](EVAL_RESULTS.md) for full run history

---

## Known Limitations

These are tracked issues identified during DB audits and pilot testing, deferred for post-pilot resolution. See [README.md — Known Limitations](README.md#known-limitations--future-work) for detail.

- Result ordering favors large organizations (alphabetical `ORDER BY`)
- `additional_info` field is effectively empty (99.7% null)
- Schedule data is sparse for most categories — open/closed filtering intentionally disabled
- Eval background task runs in the web server process
- `natural_new_to_nyc` slot extraction failure (P7 pending)
- `adversarial_fake_service` graceful handling (P6 pending)
- Phone number redaction in confirmation echo (P5 pending)
