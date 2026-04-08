# Multi-Service Intent — Architecture Plan

## Problem

The chatbot originally assumed one service type per message. Classification gated whether slot extraction even ran, leading to three ad-hoc workarounds that have now been eliminated.

## Status

| PR | Status | Description |
|---|---|---|
| PR 1 | ✅ Done | Extract all service types from a message |
| PR 2 | ✅ Done | Split classifier, extract-first routing, tone prefixes, bug fixes |
| PR 3 | Planned | Service queue — offer queued services after results |
| PR 4 | Planned | LLM extractor — update schema for multi-service |

---

## Completed: PR 1 — Extract All Service Types

**`_extract_all_service_types(text)`** scans for ALL service keywords in a message with:
- Span tracking to prevent sub-matches ("mental health" doesn't also match "health")
- Forward scanning past overlapping spans ("food stamps and food" finds both)
- Text-position ordering (user's first-mentioned service is primary)
- Category deduplication ("food" and "food pantry" → one "food" entry)

**`extract_slots(message)`** returns `additional_services` — a list of `(service_type, service_detail)` tuples beyond the primary. `merge_slots()` skips this field; `has_new_slots` checks exclude it.

**Bug fixes applied during audit:**
- `find()` only returned first occurrence — now scans forward past overlapping spans
- Order reflected keyword length, not text position — now sorted by position

**Tests:** 17 covering multi-service extraction, ordering, overlap, deduplication, additional_services in extract_slots/merge_slots.

## Completed: PR 2 — Split Classifier + Extract-First Routing

### Architecture

```
message
  ↓
┌──────────────────────────┐
│ 1. extract_slots(message)│  ← always runs first (regex, <1ms)
│    has_service_intent?   │
└───────────┬──────────────┘
            ↓
┌──────────────────────────┐
│ 2a. _classify_action()   │  → reset, greeting, confirm_yes, help, escalation, etc.
│ 2b. _classify_tone()     │  → crisis, frustrated, emotional, confused, urgent, None
└───────────┬──────────────┘
            ↓
┌──────────────────────────────────────────────────┐
│ 3. Combined routing (priority order)             │
│                                                  │
│  crisis tone           → crisis resources        │
│  reset action          → clear session           │
│  confirmations/bot/etc → action handlers         │
│  service + escalation  → service only if location│
│  service + any tone    → service + tone prefix   │
│  help (no service)     → help handler            │
│  escalation (no svc)   → escalation handler      │
│  frustrated            → frustration handler     │
│  emotional             → emotional handler       │
│  confused              → confused handler        │
│  LLM (>3 words)        → LLM classification      │
│  none                  → general conversation    │
└──────────────────────────────────────────────────┘
```

### What was removed
- `_has_service_words` — eliminated entirely
- `help_slots = extract_slots()` ad-hoc guard in help handler
- `esc_slots = extract_slots()` ad-hoc guard in escalation handler
- Second-pass emotional/confused check after slot extraction
- Double slot extraction (service section now uses `early_extracted`)

### Tone prefixes
When service intent + emotional tone are both present, the confirmation and follow-up messages get an empathetic prefix:

| Tone | Prefix |
|---|---|
| emotional | "I hear you, and I want to help." |
| frustrated | "I understand this has been frustrating. Let me try something different." |
| confused | "No worries — let me help you with that." |
| urgent | "I can see this is urgent — let me find something right away." |

Also applied to pending confirmation re-show (defensive, for future tones).

### Escalation guard
Service intent only overrides escalation when BOTH service_type AND location are present. "Connect me with a navigator about food" (food but no location) stays as escalation — the user wants human help. "Navigator, client needs shelter in East Harlem" (both present) routes to service.

### Bug fixes applied during audit
- Escalation guard regression — restored location requirement
- Tone prefix used `has_service_intent` (regex only) — changed to `category == "service"` to cover LLM-detected intent
- Tone-aware nudge prefix added to pending confirmation re-show

### Tone categories (5)
Based on research from NCBI clinical studies on homeless populations, ISEAR emotion models, and the DAPHNE social needs chatbot:

| Tone | Priority | Rationale |
|---|---|---|
| crisis | 1 | Acute danger — always wins |
| frustrated | 2 | System frustration — check before urgency |
| emotional | 3 | Sadness, fear, loneliness — covers the dominant emotional states in this population |
| confused | 4 | Overwhelm, not knowing what to do |
| urgent | 5 (lowest) | Time pressure — empathy matters more when stronger tones co-occur |

**Future tone candidates** (not blocking, easy to add later):
- `shame` — "I'm embarrassed to ask" → normalizing response. Distinct from emotional.
- Anger collapses into frustrated. Distrust into privacy bot_question. Hopelessness into emotional/crisis.

**Tests:** 40+ covering split classifier functions, combined routing, tone prefixes, escalation guard, taxonomy enrichment.

---

## Planned: PR 3 — Service Queue

### Goal
After delivering results for the first service, proactively offer the next queued service. "I need food and shelter in Brooklyn" → food results → "You also mentioned shelter — want me to search for that too?"

### Design decisions

**1. When to store the queue**

Store `_queued_services` in session when `additional_services` is non-empty in the service flow. This should happen at the point where we merge slots and proceed to confirmation — not earlier (the user might change their mind during follow-up questions).

```python
# In the service section, after merge:
additional = extracted.get("additional_services", [])
if additional:
    merged["_queued_services"] = additional
```

**2. When to offer the next service**

After `_execute_and_respond` delivers results. Append the offer to the response and replace quick replies:

```python
# In _execute_and_respond, after building the result:
queued = slots.get("_queued_services", [])
if queued:
    next_service, next_detail = queued[0]
    remaining = queued[1:]

    # Update session: remove offered service, keep remaining
    slots["_queued_services"] = remaining
    save_session_slots(session_id, slots)

    label = next_detail or _SERVICE_LABELS.get(next_service, next_service)
    result["response"] += (
        f"\n\nYou also mentioned {label} — would you like me to "
        f"search for that too?"
    )
    result["quick_replies"] = [
        {"label": f"✅ Yes, search for {label}", "value": f"I need {next_service}"},
        {"label": "❌ No thanks", "value": "No thanks"},
    ]
```

**3. How "Yes, search for shelter" works**

The quick reply sends `"I need shelter"` as a new message. This enters `generate_reply` normally:
- Extracts service_type = "shelter"
- Location, age, family_status are already in session from the previous search
- Proceeds to confirmation (or straight to search if enough info)

This is the simplest approach — no special queue-consumption logic needed. The quick reply value IS the new search request.

**4. How "No thanks" works**

"No thanks" enters `generate_reply`:
- `_classify_action` → "confirm_deny"
- No pending confirmation → falls through
- `_queued_services` should be cleared
- Show a wrap-up message

Need to add: when category is "confirm_deny" and no pending confirmation but `_queued_services` is set, clear the queue and respond gracefully:

```python
if not pending and category == "confirm_deny" and existing.get("_queued_services"):
    existing.pop("_queued_services", None)
    save_session_slots(session_id, existing)
    result = _empty_reply(
        session_id,
        "No problem! Let me know if you need anything else.",
        existing,
        quick_replies=list(_WELCOME_QUICK_REPLIES),
    )
    return result
```

**5. What "start over" does to the queue**

`clear_session` already clears all session state including `_queued_services`. No changes needed.

**6. Shared slots across queued services**

When searching for the next queued service, the session retains location, age, family_status from the previous search. This is usually correct — "I need food and shelter in Brooklyn" means both in Brooklyn. But edge cases exist:

- "I need food in Brooklyn and shelter in Manhattan" — the location would be wrong for the second service. This is a pre-existing limitation (regex extracts only one location). The user can correct via "change location" during the queued service confirmation.
- Service-specific slots like `family_status` (only relevant for shelter) should not cause issues — they're ignored by non-shelter query templates.

**7. What if the queue has 3+ services?**

After the second service's results, check if more are queued. Same logic applies recursively. In practice, 3+ services in one message is rare.

**8. What if the user ignores the queue offer and types something new?**

The new message enters `generate_reply` normally. If it has a new service_type, slots are merged (overwriting the old service_type). The queue should be cleared when a new explicit service request comes in, to avoid confusing the user with stale offers.

```python
# At the top of the service section, if new service_type differs from existing:
if (extracted.get("service_type") and existing.get("service_type")
        and extracted["service_type"] != existing["service_type"]):
    existing.pop("_queued_services", None)
```

### Files to change

| File | Change |
|---|---|
| `chatbot.py` | Store queue in service flow, offer after results, handle "no thanks", clear on new service |
| No other files | Queue is purely a chatbot session concern |

### Test scenarios

```
"I need food and shelter in Brooklyn"
  → confirms food → results → "You also mentioned shelter..."
  → "Yes" → confirms shelter → results

"I need food and shelter in Brooklyn"
  → confirms food → results → "You also mentioned shelter..."
  → "No thanks" → clears queue, wrap-up message

"I need food, clothing, and legal help in Manhattan"
  → confirms food → results → "You also mentioned clothing..."
  → "Yes" → results → "You also mentioned legal help..."

"I need food and shelter in Brooklyn" → food results → "start over"
  → clears everything including queue

"I need food and shelter in Brooklyn" → food results
  → user ignores queue offer and types "I need medical care"
  → new service replaces food, queue cleared

"I need food and shelter in Brooklyn" → food results
  → user types "that wasn't helpful"
  → frustration handler fires, queue preserved for later
```

---

## Planned: PR 4 — LLM Extractor Updates

### Current state

The LLM extractor (`extract_slots_llm`) returns a single `service_type` string. When `extract_slots_smart` calls it, the result is supplemented with regex-extracted fields including `additional_services`. This means multi-service already partially works via LLM:

1. Regex extracts: `{service_type: "food", additional_services: [("shelter", None)]}`
2. LLM extracts: `{service_type: "food"}` (single service)
3. Supplementation: regex `additional_services` is added to LLM result

So even without LLM schema changes, `additional_services` from regex is available.

### What the LLM schema change adds

The LLM could detect services that regex misses — e.g., "I need somewhere to eat and a place to crash" might not match "shelter" in regex but the LLM would understand "place to crash" = shelter.

**Option A: Array service_type** (breaking change to schema)
```python
"service_type": {
    "type": "array",
    "items": {"type": "string", "enum": [...]},
}
```
Pro: Clean. Con: Breaks existing parsing, needs migration.

**Option B: Additional field** (additive, recommended)
```python
"additional_service_types": {
    "type": "array",
    "items": {"type": "string", "enum": [...]},
    "description": "Service types beyond the primary one."
}
```
Pro: Backward compatible. Con: Two fields for the same concept.

**Recommendation:** Option B. The LLM returns `service_type` (primary) + `additional_service_types` (extras). The smart extractor merges them into the standard `additional_services` format. No breaking changes.

### Priority

Low — regex already handles the common multi-intent cases ("food and shelter", "clothing and legal help"). The LLM adds value only for indirect multi-service requests, which are rare. PR 3 (queue handling) is more impactful and should ship first.

---

## Architecture Diagram

```
User: "I'm struggling and need food and shelter in Brooklyn"
  │
  ├─ extract_slots()
  │   → service_type: "food"
  │   → additional_services: [("shelter", None)]
  │   → location: "Brooklyn"
  │
  ├─ _classify_action() → None
  ├─ _classify_tone()   → "emotional"
  │
  ├─ Combined routing
  │   → has_service_intent + emotional tone
  │   → category: "service"
  │   → tone_prefix: "I hear you, and I want to help."
  │
  ├─ Service flow
  │   → Store _queued_services: [("shelter", None)]    ← PR 3
  │   → Confirm: "I hear you, and I want to help.
  │               I'll search for food in Brooklyn."
  │
  ├─ User confirms → _execute_and_respond
  │   → DB query: food + Brooklyn
  │   → Results: 5 food services
  │   → Append: "You also mentioned shelter —           ← PR 3
  │              would you like me to search for that?"
  │
  └─ User taps "Yes, search for shelter"
      → New message: "I need shelter"
      → Location "Brooklyn" already in session
      → Confirm → execute → shelter results
```

---

## Future Improvements (not blocking)

### Eval scenarios for multi-intent
Add LLM-as-judge scenarios testing the full multi-intent flow once PR 3 ships:
- Two services extracted and both searched sequentially
- User declines queued service
- User changes location mid-queue
- Emotional + multi-service gets empathetic framing on both

### Shame tone
Research identified shame/embarrassment as a distinct emotional state in this population ("I'm embarrassed to ask", "I never thought I'd need a food bank"). Current `emotional` tone covers it but the response should normalize rather than just empathize. Easy to add: new phrase list in `_classify_tone()`, new handler with normalizing response.

### Cross-service slot conflicts
"I need food in Brooklyn and shelter in Manhattan" — only one location is extracted. Future improvement: extract per-service locations. Would require significant slot extractor changes and is rare enough to not block the queue feature.
