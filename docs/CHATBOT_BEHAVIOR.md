# Chatbot Behavior — Capabilities, Guardrails & Limitations

This document describes exactly how the YourPeer chatbot processes messages, what it can and cannot do, and the guardrails that govern its behavior. It serves as a reference for staff reviewing conversations, engineers extending the system, and stakeholders evaluating the chatbot's design.

For crisis detection details, see [CRISIS_DETECTION.md](CRISIS_DETECTION.md). For service card rendering and database queries, see [FEATURES.md](FEATURES.md).

---

## Message Routing Pipeline

Every incoming message passes through three stages: slot extraction, classification, and combined routing. Slots are always extracted first so service intent is known before routing decisions.

### Stage 1 — Slot Extraction (always runs first)

Regex-based slot extraction runs on every message before classification. This extracts service type(s), location, age, urgency, family status, and service detail. The result determines `has_service_intent` — whether the message contains a service request.

**Narrative extraction (20+ words):** Long messages are detected by `_is_narrative_message()` (≥20 words) and routed through narrative-aware extraction. With LLM enabled, `extract_slots_narrative()` uses a specialized Sonnet prompt that prioritizes by urgency hierarchy (shelter > medical > food > employment) rather than first-mention. For narratives, the LLM is fully authoritative — regex does NOT override `service_type`. This prevents "I just got out of the hospital and my housing fell through" from extracting "medical" when the user needs shelter.

**Regex-only narrative routing:** Even when `_USE_LLM=False`, narratives are routed through `_narrative_regex_fallback()` in `generate_reply`. This was a critical fix — previously, narratives only used urgency-aware extraction when the LLM was available. The fallback runs standard regex, collects all services, and re-ranks by urgency hierarchy. Context clues ("evicted", "just released", "ran away") automatically set `urgency=high`.

### Stage 2 — Split Classification

Two independent classifiers run in parallel:

**`_classify_action(text)`** — what the user wants to DO:

| Action | Trigger | Example |
|---|---|---|
| `reset` | "start over", "new search", "cancel" | "start over" |
| `bot_identity` | "are you a robot", "am I talking to a person" | "are you AI?" |
| `bot_question` | "why can't you", "how does this work", "is this private", "can ICE see" | "is this safe?" |
| `escalation` | "peer navigator", "talk to a person" | "connect with peer navigator" |
| `confirm_change_service` | "change service", "different service" | "change service" |
| `confirm_change_location` | "change location", "different area" | "change location" |
| `confirm_yes` | "yes", "sure", "go ahead", "yes search" | "yes, search" |
| `confirm_deny` | "no", "nah", "nope", "not yet" | "no" |
| `greeting` | "hi", "hello", "hey" (only if ≤3 words) | "hello" |
| `thanks` | "thank you", "thanks" (no continuation) | "thanks" |
| `help` | "what can you do", "list services"; "help" (word-boundary, excludes "helpful"/"not helpful") | "help" |

**`_classify_tone(text)`** — how the user FEELS:

| Tone | Trigger | Example |
|---|---|---|
| `crisis` | Regex + LLM crisis detection (see [CRISIS_DETECTION.md](CRISIS_DETECTION.md)) | "I want to hurt myself" |
| `frustrated` | "not helpful", "waste of time", "already tried" | "that wasn't helpful" |
| `emotional` | "feeling down", "rough day", "I'm scared", "nobody cares" | "I'm feeling really down" |
| `confused` | "I don't know what to do", "I'm overwhelmed" | "I'm lost" |
| `urgent` | "right now", "tonight", "nowhere to go", "on the street", "desperate", "kicked out today" | "I need shelter right now" |

**Key difference from the old architecture:** Tone detection has **no service-word gating**. "I'm struggling and need food" detects both emotional tone AND food service intent. The old `_has_service_words` guard that suppressed emotional detection when service words were present has been eliminated.

**`_classify_message(text)`** — backward-compatible wrapper that combines both classifiers into a single category string. Used by existing tests and the LLM fallback stage.

### Stage 3 — Combined Routing

The routing priority is:

| Priority | Condition | Route |
|---|---|---|
| 1 | `tone == crisis` | Crisis handler (always wins) |
| 2 | `action == reset` | Reset handler |
| 3 | `action` is confirmation/bot/greeting/thanks | Action handler |
| 4 | `has_service_intent == True` | **Service flow** (with tone prefix if emotional/frustrated/confused/urgent). Exception: escalation + service without location stays as escalation |
| 5 | `action == help` AND `tone != emotional` | Help handler |
| 5b | `action == help` AND `tone == emotional` | Emotional handler (emotional overrides help — "embarrassed to ask for help" is emotional, not a help menu request) |
| 6 | `action == escalation` | Escalation handler |
| 7 | `tone == frustrated` | Frustration handler |
| 8 | `tone == emotional` | Emotional handler |
| 9 | `tone == confused` | Confused handler |
| 10 | LLM classification (>3 words) | LLM-determined category |
| 10 | Looks like service request but no `service_type` | Unrecognized service redirect (3-tier escalation) |
| 11 | None of the above | General conversation |

The key insight is **row 4**: when service intent is present, it wins over help/escalation/emotional/confused. Those become tone modifiers on the service flow, not separate routes. This eliminates the ad-hoc guards that previously re-checked slots inside the help and escalation handlers.

**Escalation exception:** Service intent only overrides escalation when BOTH service_type AND location are present. "Connect me with a navigator about food" (food but no location) stays as escalation — the user wants human help. "Navigator, client needs shelter in East Harlem" (both present) routes to service — the user is making a request on behalf of someone.

**Tone prefixes applied in the service flow:**

| Tone | Prefix on confirmation/follow-up |
|---|---|
| `emotional` | "I hear you, and I want to help." |
| `emotional` (shame) | "There's no shame in that — a lot of people use these services, and reaching out takes real strength." |
| `frustrated` | "I understand this has been frustrating. Let me try something different." |
| `confused` | "No worries — let me help you with that." |
| `urgent` | "I can see this is urgent — let me find something right away." |
| None | (no prefix) |

### LLM Fallback (only when nothing else matches)

If no regex pattern matches and the message is longer than 3 words, Claude Haiku classifies the message into one of the standard categories. This catches indirect service needs ("I just got out of the hospital"), ambiguous messages, and edge cases that keyword lists can't cover.

If the LLM is unavailable or returns an unrecognized category, the system falls back to `general`.

---

## Category Behaviors

### Crisis

Crisis resources are shown immediately. The session is NOT cleared — the user can continue their service search afterward. See [CRISIS_DETECTION.md](CRISIS_DETECTION.md) for full details on the two-stage detection pipeline, six crisis categories, and fail-open policy.

**Crisis step-down:** When crisis fires on a non-acute category (`safety_concern` or `domestic_violence`) AND the user has explicit service intent (regex found a service keyword like "shelter"), the bot shows crisis resources AND preserves the extracted service slots in session. The response appends: "I can also help you find [service] in [location] — would you like me to search?" with quick replies for "Yes, search" and "Peer navigator." This handles cases like "I was kicked out and need shelter in Brooklyn" where both safety resources and practical help are appropriate. Acute crisis categories (suicide, medical, trafficking, violence) always show crisis resources only.

**Emotional phrase guard:** Before invoking the LLM for crisis detection (Stage 2), the system checks whether the message matches a known sub-crisis emotional phrase (e.g., "feeling scared", "I'm struggling", "rough day"). If so, the LLM stage is skipped entirely — these are handled by the emotional tone handler, not the crisis handler. This prevents the LLM's "when in doubt, err toward crisis=true" instruction from over-escalating clearly emotional-but-not-crisis messages.

### Reset

Clears all session state (slots, transcript, pending confirmation). Shows a fresh welcome message with service category buttons. Triggered by "start over", "new search", "begin again", or "cancel".

### Bot Identity

Responds honestly that the user is talking to an AI assistant, offers to connect with a real person (peer navigator). Shows service category buttons so the user can continue.

### Bot Question

Answers questions about the bot's capabilities using the **`bot_knowledge.py` self-knowledge module** — a single source of truth for both the LLM prompt and static handler.

**Architecture:** The module sources capability data from actual code at runtime:
- Service categories from `slot_extractor.SERVICE_KEYWORDS`
- PII types from `pii_redactor._PLACEHOLDERS`
- Location count from `slot_extractor._KNOWN_LOCATIONS`

This prevents drift between what the code does and what the bot tells users it does.

**15 topics** organized by priority: privacy_ice > privacy_police > privacy_benefits > privacy_visibility > privacy_delete > privacy_identity > privacy_general > location_fail > location_how > coverage > services > how_it_works > crisis_support > peer_navigator > limitations > language. Priority ordering ensures multi-topic collisions resolve correctly (e.g., "Is my location data private?" → privacy, not location).

**LLM path:** `_build_bot_question_prompt()` calls `build_capability_context()` which generates the "Facts about yourself" section from live code data, including service categories, PII redaction types, location count, crisis detection capabilities, and emotional handling.

**Static path:** `_static_bot_answer()` calls `answer_question()` which keyword-matches against topic entries. Unknown questions get a useful generic answer.

**Phrase expansion:** `_BOT_QUESTION_PHRASES` includes 13 privacy/information-handling phrases for the `wa_privacy_information_sharing` eval scenario ("what happens to my information", "what do you do with my data", etc.).

### Escalation

Provides contact information for Streetlives peer navigators and crisis resources. Clears any pending search confirmation so the user doesn't accidentally re-enter the search flow on their next message. Sets `_last_action = "escalation"` so that "no" on the next message is interpreted as "no, I don't need the navigator" rather than "no, don't run the search."

### Confirmation Actions

Four confirmation categories handle the user's response to a pending search confirmation:

- **confirm_yes** — Executes the database query and returns service cards.
- **confirm_deny** — If the deny message contains a NEW service type different from the current one (e.g., "no, I need shelter instead"), re-extracts slots and shows new confirmation. Otherwise, clears the confirmation, keeps slots, offers options (change service, change location, new search, peer navigator). "wait" and "hold on" are intentionally NOT deny phrases — they're interruptions that would otherwise lose embedded service changes like "wait, I changed my mind, I need shelter."

### Implicit Service Change Detection (Pending Confirmation)

When a confirmation is pending, any message with a DIFFERENT `service_type` from the pending one is treated as an implicit correction — no denial keyword needed. This follows the industry standard (Rasa, Microsoft CLU, Dialogflow) of slot-level conflict detection.

**Change vs Add distinction:** Additive keywords ("also", "too", "as well", "in addition", "plus") signal ADD intent — the new service is queued rather than replacing the current one. Without additive keywords, a different service_type is treated as a CHANGE.

**Negation-blind regex handling:** When the user says "Not food, I need shelter," regex extracts both "food" (primary, from negated mention) and "shelter" (additional). During pending confirmation, if the primary matches the current service but an additional service differs, the system swaps the additional to primary — the user is correcting, not confirming. This swap is also applied in the confirm_deny handler for messages like "I don't want food, shelter please."
- **confirm_change_service** — Clears the service type slot and asks what they need.
- **confirm_change_location** — Clears the location slot and offers borough buttons.

Context-aware "yes" and "no": after an escalation or emotional response, "yes" and "no" refer to the peer navigator offer, not to a pending search. "Yes" after escalation or emotional shows a distinct confirmation response ("Here's how to reach a peer navigator right now:") with actionable contact details — deliberately different from the initial escalation message so the user sees progress rather than repetition. Also shows service category buttons so the user can continue. "No" after escalation gives a gentle "I'm here if you change your mind." "No" after emotional gives "That's okay. I'm here whenever you're ready." This prevents a user who just shared something vulnerable from accidentally triggering a search confirmation.

**`_last_action` lifecycle rules:** The `_last_action` session variable tracks conversational context so that "yes"/"no" can be interpreted correctly. It follows strict lifecycle rules:

- **Set by context-preserving handlers:** emotional, escalation, frustration, confused, crisis — these create a context where the next "yes"/"no" has a specific meaning.
- **Cleared by context-shift handlers:** help, greeting, thanks, reset — these represent the user moving on. After these, "yes"/"no" should not connect to a navigator from a previous emotional/escalation context.
- **Cleared by yes/no handlers themselves:** after interpreting "yes" or "no" in context, the handler clears `_last_action` to prevent stale context.
- **Not set by service flow:** service confirmations use `_pending_confirmation`, not `_last_action`.

This lifecycle prevents the anti-pattern where emotional→help→"yes" incorrectly connects to a navigator (the user asked for help, not a navigator).

### Greeting

Returns a warm welcome. If the user has existing slots from an earlier search, acknowledges this and asks if they want to continue or start over.

### Thanks

Returns a brief "you're welcome" message with service buttons in case the user wants to search for something else.

### Frustration

Acknowledges the frustration empathetically without being defensive. Offers three options: try a different search, connect with a peer navigator, or call 311 for live social services help. Sets `_last_action = "frustration"` so "yes" connects to a peer navigator (the handler's messaging pushes toward navigator: "I think a peer navigator would be more helpful") and the "Try different search" button sends "Start over" directly via quick reply.

**Repeated frustration detection:** Uses a `_frustration_count` counter that increments on every frustration message and persists in session. When count ≥ 2, the bot produces a shorter, different response that avoids repeating the same wall of text. The counter is more robust than checking `_last_action` alone, since `_last_action` could be cleared by intermediate handlers (search results, queue offers). The second response acknowledges the bot isn't helping, strongly recommends a peer navigator, and mentions 311 as a backup.

### Emotional

Follows the **Acknowledge-Validate-Redirect (AVR)** pattern established in the clinical chatbot literature (see [Emotional Handling Design](#emotional-handling-design) below). Acknowledges the user's feelings with warmth before doing anything else. Uses an LLM-generated response when available, with a specialized prompt that focuses on empathy and explicitly prohibits listing services, giving advice, or diagnosing. Falls back to emotion-specific static responses that validate the particular feeling expressed.

**Emotion-specific responses:** The static fallback uses `_pick_emotional_response(text)` to select from six tailored responses based on the emotion detected:

| Emotion | Trigger Examples | Response Style |
|---|---|---|
| Scared | "I'm scared", "really scared" | Names the fear, normalizes it, offers navigator |
| Sad | "feeling down", "feeling sad" | Validates not being okay, no rush |
| Rough day | "rough day", "hard time" | Acknowledges heaviness, gentle presence |
| Shame | "embarrassed to ask", "never thought I'd need" | Normalizes help-seeking, affirms strength |
| Grief | "lost someone", "grieving" | Acknowledges loss, no rush |
| Isolation | "I have no one", "completely alone" | Validates visibility, affirms courage |

If no specific emotion is matched, a warm generic response is used. All responses avoid mentioning specific services — per AVR research, pushing services after emotional disclosure feels dismissive.

**Emotional tone overrides help action:** When the message contains both emotional tone and the word "help" (e.g., "I'm embarrassed to ask for help"), the emotional handler takes priority over the help menu. The word "help" is incidental to the emotional expression, not a request for the service menu.

Only shows a "Talk to a person" quick reply — no service category buttons. This prevents the experience of sharing something vulnerable and immediately being shown a service menu. Sets `_last_action = "emotional"` so that "yes" on the next message routes to the peer navigator, and "no" gives a gentle non-pushy response with only a navigator button (not the full service menu — per the AVR principle of not pushing task-oriented responses after emotional distress).

### Confused

Shows gentle guidance for users who don't know what they need. Lists common things people look for in plain language (not service category labels). Shows category buttons plus a "Talk to a person" option. Sets `_last_action = "confused"` so "yes" connects to a peer navigator and "no" gives gentle encouragement with a navigator button. This handler is intentionally NOT sent to the LLM, which would misinterpret "I don't know what to do" as a mental health service request.

### Help

Returns a static response describing what the bot can do: find free services in NYC, the categories available, and how to get started. Shows service category buttons.

### Context-Aware Yes/No

After emotional, escalation, frustration, or confused responses, "yes" and "no" are interpreted in context rather than as search confirmations:

| After | "Yes" means | "No" means |
|---|---|---|
| Emotional | Connect to peer navigator | Gentle response + navigator button only (no service menu) |
| Escalation | Connect to peer navigator | "No problem" + service menu buttons |
| Frustration | Connect to peer navigator | "No worries" + navigator button |
| Confused | Connect to peer navigator | Gentle encouragement + navigator button |
| Crisis (step-down) | Execute service search with preserved slots | Acknowledge + navigator button |

The `_last_action` tracker is cleared after any non-yes/no message so it doesn't persist indefinitely.

### Service

Extracts structured slots (service type, service detail, location, age, urgency, gender, family status) from the message. If slots are complete, shows a confirmation prompt. If incomplete, asks a follow-up question for the missing slot.

**Family composition:** For shelter searches, the chatbot asks "Are you on your own, or do you have family or children with you?" after collecting age. The `family_status` slot (with_children, with_family, alone) is shown in the confirmation and used to enrich shelter taxonomy queries.

**Multi-service extraction:** The slot extractor detects all service types in a message (e.g., "food and shelter" → both extracted). The primary type drives the current search; additional types are stored in `additional_services` for future queue handling.

### General

Catch-all for messages that don't fit any other category. Uses Claude Haiku for a natural conversational response. The prompt adapts based on context:

- **With service intent** (user has partially filled slots): gently reminds them they can continue their search.
- **Without service intent**: just responds naturally without pushing services.
- **Unrecognized service request** (user has a location but no recognized service type after 2+ turns): redirects gracefully with "I'm not sure I can help with that specifically, but I can search for services in [location]" and shows the full service menu. This handles requests for impossible services (e.g., "helicopter ride") that would otherwise loop indefinitely.

Service category buttons are only shown on the first conversational turn when the user has no service intent. After that, general responses have no buttons to avoid feeling transactional.

---

## LLM Usage

Three LLM-powered features are used in production, each with a specific model assignment:

| Feature | Model | When It Runs | Output |
|---|---|---|---|
| Conversational fallback | Haiku | Message classified as `general` | 1–3 sentence response |
| Slot extraction | Sonnet | Complex service messages (regex handles simple ones) | JSON: service_type, location, age, urgency, gender, family_status |
| Narrative extraction | Sonnet | Long messages (≥20 words) with multiple service needs | Same JSON, urgency-prioritized: shelter > medical > food > employment |
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

## Emotional Handling Design

### The Acknowledge-Validate-Redirect (AVR) Pattern

The chatbot's emotional handling follows the **Acknowledge-Validate-Redirect** pattern, the dominant design approach across clinically validated mental health chatbots. This pattern has three steps:

1. **Acknowledge** the emotion immediately ("I hear you")
2. **Validate** it ("You don't have to have everything figured out")
3. **Redirect** gently — to a human (peer navigator) or practical help, but only after steps 1-2

This pattern is informed by research across several domains relevant to our population:

**Clinical chatbot research.** Woebot (CBT-based, RCT-validated) and Wysa (CBT/DBT, hybrid human+AI) both prioritize empathetic acknowledgment before any task-oriented response. A 2025 JMIR study analyzing 13,700 utterances across 8 commercial chatbots found that social chatbots excelling at empathy (SimSimi, Replika) detected emotional tone before processing intent, and that users expected chatbots to provide "a safe space to express emotions" before receiving information or advice (Chin et al., *JMIR Formative Research*, 2025).

**Social services chatbot research.** The DAPHNE chatbot (Dialog-Based Assistant Platform for Healthcare and Needs Ecosystem), designed for social need screening with low-income families, found that "fostering user confidence" was a crucial design factor and that users valued empathetic conversational design over task efficiency (Sezgin et al., *JMIR Human Factors*, 2024).

**Emotional distress in vulnerable populations.** A PMC study on chatbot use across 8 countries found that 75% of depression-related chatbot interactions involved expressing feelings rather than seeking strategies, suggesting users find relief in being heard before being helped (Chin et al., *PMC*, 2023). A Frontiers study on empathic chatbots demonstrated that empathetic responses significantly improved mood after social exclusion compared to merely acknowledging responses (Ischen et al., *Frontiers in Psychology*, 2019).

### Design Principles Applied

Based on this research, the following principles govern emotional handling in the YourPeer chatbot:

1. **Emotion detection runs before intent classification.** The split classifier (`_classify_tone`) runs independently of slot extraction. This ensures emotional phrases like "I'm feeling scared" are recognized even when service keywords are also present.

2. **Don't push services on emotional users.** When someone expresses distress ("I'm feeling really down"), the response shows empathy and offers a peer navigator — no service category buttons. The emotional deny handler ("no" after emotional response) also avoids the full service menu, showing only a navigator button.

3. **Emotional phrases are not service keywords.** Words like "struggling", "having a hard time", and "stressed" were removed from the `mental_health` service keyword list. "stress" uses word-boundary matching (`\bstress\b`) so "I need help with stress" matches but "I'm stressed out" does not. This prevents emotional expressions from being misrouted to service search.

4. **Sub-crisis emotional phrases skip LLM crisis detection.** The LLM crisis detector is instructed to "err toward crisis=true" for ambiguous messages — appropriate for genuine safety ambiguity, but over-escalatory for clearly emotional phrases. A guard in `crisis_detector.py` checks for known sub-crisis emotional phrases before invoking the LLM, routing them to the emotional handler instead.

5. **Graduated response levels.** The system has three tiers of emotional response:
   - **Pure emotional** (no service intent): Full AVR response with navigator offer, no service buttons
   - **Emotional + service intent**: Empathetic tone prefix ("I hear you, and I want to help.") followed by service confirmation
   - **Crisis + service intent**: Crisis resources shown with step-down offer to search for the mentioned service

6. **Always offer human escalation.** Every emotional response includes a path to a peer navigator. This aligns with Wysa's hybrid model and the APA's guidance that AI chatbots should "complement—not replace—human-led" support.

### Implementation: Static Scaffold + LLM Enhancement (Option 3)

The emotional handler uses a **whitelist approach** rather than relying on the LLM to generate the full response. This was adopted after evaluations showed the LLM consistently pushed services despite prompt constraints — the system identity ("helps people find free social services") biased the LLM toward service-finding behavior.

**Flow:**
1. `_pick_emotional_response(message)` returns a static response matched to one of 6 emotion types (scared, sad, rough_day, shame, grief, alone). This is ALWAYS the base response.
2. If `_USE_LLM` is True, `_generate_emotional_enhancement(message)` asks the LLM for ONE optional personalized sentence (max 15 words) that references something specific the user said.
3. The enhancement is validated by `_validate_emotional_enhancement()` against a 56-item blocklist of service words, soft-push phrases, steering questions, and vague service hints.
4. If valid, the enhancement is inserted between the acknowledgment paragraph and the navigator offer paragraph. If invalid or "NONE", the static response stands alone.

**Why whitelist beats blacklist:** Option 2 (validate-and-reject full LLM response) was rejected because it relies on a blacklist catching every possible service push. The LLM generates novel phrasings ("I'm here to assist you," "there are options available") that pass keyword validation but still score poorly with evaluators. Option 3's static response is guaranteed correct; the enhancement can only improve it.

**Blocklist categories:** `_EMOTIONAL_ENHANCEMENT_BLOCKLIST` contains: explicit service words (15), soft-push phrases (11), steering questions (7), service-adjacent terms (6), vague service hints (10).

### References

- Chin, H., Song, H., et al. (2025). Chatbots' Empathetic Conversations and Responses: A Qualitative Study of Help-Seeking Queries on Depressive Moods Across 8 Commercial Conversational Agents. *JMIR Formative Research*, 9(1), e71538. https://formative.jmir.org/2025/1/e71538
- Chin, H., Peng, H., et al. (2023). The Potential of Chatbots for Emotional Support and Promoting Mental Well-Being in Different Cultures. *Journal of Medical Internet Research*, 25, e48592. https://pmc.ncbi.nlm.nih.gov/articles/PMC10625083/
- Sezgin, E., et al. (2024). Chatbot for Social Need Screening and Resource Sharing With Vulnerable Families: Iterative Design and Evaluation Study. *JMIR Human Factors*, 11, e57114. https://humanfactors.jmir.org/2024/1/e57114
- Ischen, C., et al. (2019). Effectiveness of an Empathic Chatbot in Combating Adverse Effects of Social Exclusion on Mood. *Frontiers in Psychology*, 10, 3061. https://www.frontiersin.org/articles/10.3389/fpsyg.2019.03061
- American Psychological Association. (2025). Health Advisory: Use of Generative AI Chatbots and Wellness Applications for Mental Health. https://www.apa.org/topics/artificial-intelligence-machine-learning/health-advisory-chatbots-wellness-apps

---

## Known Limitations

### Unrecognized Service Requests

When the user asks for something that doesn't match any service category (e.g., "helicopter ride", "asdfghjkl"), the handler uses a three-tier escalation pattern:

| Tier | Trigger | Response | Quick Replies |
|---|---|---|---|
| 1st | First unrecognized | LLM acknowledges specific request + lists available categories (static fallback: "I don't have information about that specifically, but I can search for...") | Service category buttons |
| 2nd | Second unrecognized | Shorter + navigator push | Category buttons + navigator |
| 3rd+ | Third+ unrecognized | Just navigator push | Navigator + start over |

**Detection:** Fires when `service_type` is None AND any of: (a) location extracted without service, (b) request verb + transcript ≥ 2, (c) `_unrecognized_count ≥ 1` (sticky — once flagged, subsequent messages continue incrementing). **LLM "other" interception:** When the LLM extractor returns `service_type="other"` without a `service_detail`, AND the regex extractor also returned None, the system treats it as unrecognized rather than searching for "other services." This distinguishes genuinely unrecognizable requests ("helicopter ride" → regex=None, LLM="other") from legitimate "other" category requests ("SNAP benefits" → regex="other", LLM="other"). **Recovery:** User can exit by choosing a real service category at any time. Reset clears the counter. **LLM prompt:** When available, the LLM generates a warm redirect that names the specific thing the user asked for and explains what IS available, rather than a generic "I can't help with that."

### Conversational

- **English only.** Multi-language support (Spanish minimum) is planned but not implemented.
- **No memory across sessions.** Each session is independent. The bot cannot reference previous visits.
- **Emotional detection phrase coverage.** Common emotional phrases ("feeling down", "I'm scared", "rough day") are caught by regex. Indirect or culturally specific expressions fall through to the LLM classifier. Without an API key (regex-only mode), only the explicit phrase list is active. The emotional phrase guard in `crisis_detector.py` prevents known sub-crisis emotional phrases from being over-escalated to crisis by the LLM. Keywords that could collide between emotional expressions and service requests (e.g., "stress" matching "stressed out") use word-boundary matching to prevent false positives.
- **Shame tone uses emotional handler with specialization, not a dedicated handler.** Shame phrases ("embarrassed to ask", "never thought I'd need help") are detected and routed to the emotional handler which provides a shame-specific normalizing response ("You have nothing to be ashamed of. A lot of people use these services."). When shame co-occurs with service intent, the tone prefix normalizes instead of the generic "I hear you." A fully dedicated shame handler with specialized follow-up questions is planned for a future iteration.

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

Add to `_EMOTIONAL_PHRASES` in `chatbot.py`. Avoid phrases that overlap with service keywords ("feeling hungry" should route to food service, not emotional acknowledgment). Add a test case to `test_emotional_classification`. Thanks to contraction normalization, you only need the expanded form — e.g., adding "not okay" will automatically match "isn't okay", "wasnt okay", "aren't okay", etc.

### Contraction normalization

`_normalize_contractions()` in `chatbot.py` expands 37 common contractions (e.g., "isn't" → "is not", "i'm" → "i am") before phrase matching in `_classify_tone()` and the help negators in `_classify_action()`. This means phrase lists only need the expanded "not" form to match all contraction variants. Normalization is NOT applied to crisis detection — crisis uses explicit enumeration for safety. To add a new contraction, add it to `_CONTRACTION_MAP` in `chatbot.py` and add a test in `test_contraction_normalization.py`.

### Intensifier stripping

`_strip_intensifiers()` in `chatbot.py` removes 20 common intensifier adverbs (really, very, so, super, extremely, pretty, quite, totally, absolutely, incredibly, truly, deeply, terribly, horribly, awfully, genuinely, particularly, just, kinda, sorta) before phrase matching in `_classify_tone()` and `_classify_message()`. This means "I'm really scared" → "I'm scared" matches the phrase "i'm scared" without needing an explicit "really scared" entry. Stripping is NOT applied to crisis detection. "not" and other negation words are never stripped — they change meaning. To add a new intensifier, add it to `_INTENSIFIERS` in `chatbot.py`.

### Modifying guardrails

LLM guardrails are embedded in three prompt builders in `chatbot.py`:
- `_build_conversational_prompt()` — general conversation
- `_build_empathetic_prompt()` — emotional acknowledgment
- `_build_bot_question_prompt()` — capability questions

Each prompt contains a "STRICT RULES" or "Guidelines" section that instructs the LLM on what to avoid. Changes to guardrail language should be tested by running the LLM-as-judge eval suite to verify they don't cause regressions.

### Testing

Conversation routing is covered by 151 tests in `test_chatbot.py`, 39 structural fix tests in `test_structural_fixes.py`, 118 phrase audit tests in `test_phrase_audit.py`, 161 contraction/intensifier normalization tests in `test_contraction_normalization.py`, 29 edge-case tests in `test_edge_cases.py`, 36 crisis detection tests in `test_crisis_detector.py`, and 80 PII redaction tests in `test_pii_redactor.py`. Use `assert_classified(message, category)` from `conftest.py` for classification tests and `send(message)` for full routing tests.

```bash
# Run conversation tests
pytest tests/test_chatbot.py -v

# Run a specific category
pytest tests/test_chatbot.py -k "emotional" -v

# Full suite
pytest tests/ -q
```
