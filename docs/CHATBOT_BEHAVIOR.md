# Chatbot Behavior — Capabilities, Guardrails & Limitations

This document describes exactly how the YourPeer chatbot processes messages, what it can and cannot do, and the guardrails that govern its behavior. It serves as a reference for staff reviewing conversations, engineers extending the system, and stakeholders evaluating the chatbot's design.

For crisis detection details, see [CRISIS_DETECTION.md](CRISIS_DETECTION.md). For service card rendering and database queries, see [FEATURES.md](FEATURES.md).

---

## Message Routing Pipeline

Every incoming message passes through a two-stage classifier that determines how it should be handled. The classifier runs before any response is generated.

### Stage 1 — Regex (< 1ms, always runs)

Deterministic keyword and phrase matching. Handles button taps, short phrases, and unambiguous patterns where the LLM would add latency without improving accuracy. The checks run in this order — first match wins:

| Priority | Category | Trigger | Example |
|---|---|---|---|
| 1 | `crisis` | Regex + LLM crisis detection (see [CRISIS_DETECTION.md](CRISIS_DETECTION.md)) | "I want to hurt myself" |
| 2 | `reset` | "start over", "new search", "cancel" | "start over" |
| 3 | `bot_identity` | "are you a robot", "am I talking to a person" | "are you AI?" |
| 4 | `bot_question` | "why can't you", "how does this work", "what can you search" | "why couldn't you get my location?" |
| 5 | `escalation` | "peer navigator", "talk to a person", "talk to someone" | "connect with peer navigator" |
| 6 | `confirm_change_service` | "change service", "different service" | "change service" |
| 7 | `confirm_change_location` | "change location", "different area" | "change location" |
| 8 | `confirm_yes` | "yes", "sure", "go ahead", "search", "yes search" | "yes, search" |
| 9 | `confirm_deny` | "no", "nah", "nope", "not yet", "maybe later" | "no" |
| 10 | `greeting` | "hi", "hello", "hey" (only if ≤3 words) | "hello" |
| 11 | `thanks` | "thank you", "thanks" (only if no continuation like "but") | "thanks" |
| 12 | `frustration` | "not helpful", "waste of time", "didn't work", "already tried" | "that wasn't helpful" |
| 13 | `emotional` | "feeling down", "having a rough day", "I'm scared", "nobody cares" (only if no service-intent words like "need", "find", "treatment") | "I'm feeling really down" |
| 14 | `confused` | "I don't know what to do", "I'm overwhelmed", "where do I start" (only if no service-intent words) | "I'm lost" |
| 15 | `help` | "help", "list services", "what is this" | "help" |
| 16 | `service` | Slot extraction finds a service keyword (food, shelter, etc.) | "I need food in Brooklyn" |
| 17 | `emotional` / `confused` (second pass) | Emotional/confused phrases that were skipped at step 13–14 because of service words, but slot extraction found no actual slots | "I need to feel better" |

### Stage 2 — LLM (only when Stage 1 returns "general")

If no regex pattern matches and the message is longer than 3 words, Claude Haiku classifies the message into one of the same categories. This catches indirect service needs ("I just got out of the hospital"), ambiguous messages, and edge cases that keyword lists can't cover.

If the LLM is unavailable or returns an unrecognized category, the system falls back to `general`.

---

## Category Behaviors

### Crisis

Crisis resources are shown immediately. The session is NOT cleared — the user can continue their service search afterward. See [CRISIS_DETECTION.md](CRISIS_DETECTION.md) for full details on the two-stage detection pipeline, six crisis categories, and fail-open policy.

### Reset

Clears all session state (slots, transcript, pending confirmation). Shows a fresh welcome message with service category buttons. Triggered by "start over", "new search", "begin again", or "cancel".

### Bot Identity

Responds honestly that the user is talking to an AI assistant, offers to connect with a real person (peer navigator). Shows service category buttons so the user can continue.

### Bot Question

Answers questions about the bot's capabilities directly and honestly. Uses an LLM prompt loaded with factual information about the system: searches a verified NYC services database, covers five boroughs only, uses browser geolocation (requires permission), doesn't store personal information. Falls back to a static capabilities summary when the LLM is unavailable.

This category catches messages like "why weren't you able to get my location?" that previously misrouted to the frustration handler.

### Escalation

Provides contact information for Streetlives peer navigators and crisis resources. Clears any pending search confirmation so the user doesn't accidentally re-enter the search flow on their next message. Sets `_last_action = "escalation"` so that "no" on the next message is interpreted as "no, I don't need the navigator" rather than "no, don't run the search."

### Confirmation Actions

Four confirmation categories handle the user's response to a pending search confirmation:

- **confirm_yes** — Executes the database query and returns service cards.
- **confirm_deny** — Clears the confirmation, keeps slots, offers options (change service, change location, new search, peer navigator).
- **confirm_change_service** — Clears the service type slot and asks what they need.
- **confirm_change_location** — Clears the location slot and offers borough buttons.

Context-aware "yes" and "no": after an escalation or emotional response, "yes" and "no" refer to the peer navigator offer, not to a pending search. "Yes" after escalation or emotional shows the peer navigator contact info. "No" after escalation gives a gentle "I'm here if you change your mind." "No" after emotional gives "That's okay. I'm here whenever you're ready." This prevents a user who just shared something vulnerable from accidentally triggering a search confirmation.

### Greeting

Returns a warm welcome. If the user has existing slots from an earlier search, acknowledges this and asks if they want to continue or start over.

### Thanks

Returns a brief "you're welcome" message with service buttons in case the user wants to search for something else.

### Frustration

Acknowledges the frustration empathetically without being defensive. Offers three options: try a different search, connect with a peer navigator, or call 311 for live social services help. Does NOT re-show the same results or push the user to retry the same query.

### Emotional

Acknowledges the user's feelings with warmth before doing anything else. Uses an LLM-generated response when available, with a specialized prompt that focuses on empathy and explicitly prohibits listing services, giving advice, or diagnosing. Falls back to a static response that validates the feeling, offers peer navigator, and gently mentions practical help is available.

Only shows a "Talk to a person" quick reply — no service category buttons. This prevents the experience of sharing something vulnerable and immediately being shown a service menu. Sets `_last_action = "emotional"` so that "yes" on the next message routes to the peer navigator, and "no" gives a gentle non-pushy response.

### Confused

Shows gentle guidance for users who don't know what they need. Lists common things people look for in plain language (not service category labels). Shows category buttons plus a "Talk to a person" option. This handler is intentionally NOT sent to the LLM, which would misinterpret "I don't know what to do" as a mental health service request.

### Help

Returns a static response describing what the bot can do: find free services in NYC, the categories available, and how to get started. Shows service category buttons.

### Service

Extracts structured slots (service type, location, age, urgency, gender) from the message. If slots are complete, shows a confirmation prompt. If incomplete, asks a follow-up question for the missing slot.

### General

Catch-all for messages that don't fit any other category. Uses Claude Haiku for a natural conversational response. The prompt adapts based on context:

- **With service intent** (user has partially filled slots): gently reminds them they can continue their search.
- **Without service intent**: just responds naturally without pushing services.

Service category buttons are only shown on the first conversational turn when the user has no service intent. After that, general responses have no buttons to avoid feeling transactional.

---

## LLM Usage

Three LLM-powered features are used in production, each with a specific model assignment:

| Feature | Model | When It Runs | Output |
|---|---|---|---|
| Conversational fallback | Haiku | Message classified as `general` | 1–3 sentence response |
| Slot extraction | Haiku | Complex service messages (regex handles simple ones) | JSON: service_type, location, age, urgency, gender |
| Message classification | Haiku | Messages >3 words that regex can't classify | Single category name |
| Emotional acknowledgment | Haiku | Messages classified as `emotional` | 2–3 sentence empathetic response |
| Bot question answer | Haiku | Messages classified as `bot_question` | 2–3 sentence factual answer |
| Crisis detection (Stage 2) | Sonnet | Ambiguous messages where regex didn't fire | JSON: {crisis: bool, category: string} |

See the Model Analysis tab in the admin console for cost/capability analysis and the rationale for each model assignment.

---

## Guardrails

### The bot must never:

- **Fabricate service information.** All service names, addresses, phone numbers, hours, fees, and eligibility rules come from the Streetlives database via parameterized SQL templates. The LLM never generates service data.

- **Give specific medical, legal, psychological, or financial advice.** The bot does not diagnose conditions, suggest treatments, recommend legal strategies, or advise on financial decisions. For anything requiring professional judgment, it directs the user to a peer navigator.

- **Make promises about service availability or eligibility.** Service data comes from the database but may be outdated. The bot shows what's in the database without guaranteeing the service is currently operating or that the user qualifies.

- **Encourage specific life decisions.** The bot does not tell users what they should do — it helps them find resources so they can make their own decisions.

- **Share personal opinions or take sides.** The bot is neutral and supportive. It does not comment on a user's situation, judge their choices, or express opinions.

- **Store personally identifiable information.** PII (names, phone numbers, SSNs, emails, addresses) is redacted from all stored transcripts before they reach the audit log. Session state is ephemeral (30-minute TTL, in-memory only).

- **Generate crisis resources from the LLM.** All crisis hotline numbers and resources are static strings embedded in the code, never LLM-generated. This ensures they are accurate, reviewed, and consistent.

### The bot should always:

- **Acknowledge emotions before steering.** When a user shares something emotional, the bot validates their feeling first. It does not immediately redirect to services.

- **Offer the peer navigator.** For situations requiring human judgment (complex needs, emotional distress, frustration with the system), the bot proactively offers to connect the user with a peer navigator.

- **Fail open on safety.** If the LLM is unavailable during crisis detection, the system returns a general safety response with hotline numbers rather than falling through to normal conversation.

- **Confirm before querying.** The bot always shows the user what it will search for (service type + location) and waits for explicit confirmation before executing a database query.

- **Be honest about its limitations.** When asked what it can and can't do, the bot answers directly rather than deflecting.

---

## Conversation Modes

The bot operates in two implicit modes based on whether the user has expressed a service need:

### Service search mode

Entered when slot extraction detects a service type, location, or other structured field. The bot focuses on completing the intake: asking follow-up questions for missing slots, confirming search parameters, executing the query, and presenting results. Quick-reply buttons guide the user through each step.

### Just chatting mode

Active when the user hasn't expressed a service need (or has finished a search and is continuing the conversation). The bot responds naturally without pushing services. It can handle 2–3 conversational turns without trying to convert them into a service search. Service category buttons are not shown repeatedly — they appear on the welcome message, after a reset, or when the user explicitly asks what's available.

The transition between modes is automatic: any message containing a service keyword or slot data switches to service search mode.

---

## Known Limitations

### Conversational

- **Single-intent only.** The bot cannot handle "I need food AND shelter" in one message. It picks the first service type detected and ignores the second.
- **English only.** Multi-language support (Spanish minimum) is planned but not implemented.
- **No memory across sessions.** Each session is independent. The bot cannot reference previous visits.
- **Emotional detection uses the same two-stage pattern as crisis detection.** Common emotional phrases are caught by regex (<1ms). Indirect or culturally specific expressions (e.g., "I've been having the worst week and I just don't see things getting better") fall through to the LLM classifier, which can return `emotional` as a category. Without an API key (regex-only mode), only the explicit phrase list is active.

### Search & Results

- **NYC only.** The bot cannot search for services outside New York City's five boroughs.
- **Schedule data is sparse.** Most service categories show "Call for hours" because the database lacks schedule coverage. Open/closed filtering is intentionally disabled to avoid silently excluding services.
- **No real-time availability.** Service data is as fresh as the last database update. The bot cannot verify whether a service is currently operating or has capacity.
- **Result ordering is approximate.** Results are sorted by open-now, then recently verified, then name. Proximity sorting is available only when browser geolocation is provided.

### Technical

- **In-memory session store.** Sessions are lost on server restart. Chat history persistence (localStorage) mitigates this for the user's message display, but the backend slots are gone.
- **In-memory audit log.** All metrics data resets on server restart. Persistent storage is planned for post-pilot.
- **LLM dependency for nuanced cases.** When `ANTHROPIC_API_KEY` is not set, the bot runs in regex-only mode: no LLM classification, no LLM slot extraction, no LLM conversational responses, and crisis detection is limited to regex patterns only.

---

## Extending the Chatbot

### Adding a new routing category

1. Add a phrase list constant in `chatbot.py` (e.g., `_NEW_CATEGORY_PHRASES`)
2. Add detection in `_classify_message` at the appropriate priority level
3. Add a response constant or LLM prompt builder
4. Add routing in `generate_reply`
5. Add the category to `_CLASSIFY_SYSTEM_PROMPT` and the `valid` set in `claude_client.py`
6. Add tests: classification tests, routing tests, false-positive guards

### Adding new emotional phrases

Add to `_EMOTIONAL_PHRASES` in `chatbot.py`. Avoid phrases that overlap with service keywords ("feeling hungry" should route to food service, not emotional acknowledgment). Add a test case to `test_emotional_classification`.

### Modifying guardrails

LLM guardrails are embedded in three prompt builders in `chatbot.py`:
- `_build_conversational_prompt()` — general conversation
- `_build_empathetic_prompt()` — emotional acknowledgment
- `_build_bot_question_prompt()` — capability questions

Each prompt contains a "STRICT RULES" or "Guidelines" section that instructs the LLM on what to avoid. Changes to guardrail language should be tested by running the LLM-as-judge eval suite to verify they don't cause regressions.

### Testing

Conversation routing is covered by 63 tests in `test_chatbot.py`, 29 edge-case tests in `test_edge_cases.py`, and 36 crisis detection tests in `test_crisis_detector.py`. Use `assert_classified(message, category)` from `conftest.py` for classification tests and `send(message)` for full routing tests.

```bash
# Run conversation tests
pytest tests/test_chatbot.py -v

# Run a specific category
pytest tests/test_chatbot.py -k "emotional" -v

# Full suite
pytest tests/ -q
```
