# Multi-Service Intent — Architecture Plan

## Problem

The chatbot currently assumes one service type per message. Classification gates whether slot extraction even runs, leading to three ad-hoc workarounds:

1. `_has_service_words` hardcoded word list in `_classify_message()` — gates emotional/confused
2. `help_slots = extract_slots()` in help handler — re-classifies to service
3. `esc_slots = extract_slots()` in escalation handler — re-classifies to service

This breaks when a user says "I need food and shelter in Brooklyn" (only food extracted), or "I'm really struggling, I need shelter" (might classify as emotional, ignoring the shelter request entirely).

## Proposed Architecture: Extract First, Classify Tone, Route by Both

### Phase 1 — Extract all service types (slot_extractor.py)

**`_extract_all_service_types(text)`** — returns a list of `(service_type, service_detail)` tuples instead of the first match.

```python
# "I need food and shelter" → [("food", None), ("shelter", None)]
# "I need dental care" → [("medical", "dental care")]
# "hello" → []
```

**`extract_slots(message)`** — returns:
```python
{
    "service_type": "food",           # primary (first match)
    "service_detail": None,
    "additional_services": [          # NEW: remaining matches
        ("shelter", None),
    ],
    "location": "Brooklyn",
    "age": None,
    "family_status": None,
    "urgency": None,
}
```

### Phase 2 — Classify tone separately (chatbot.py)

New function `_classify_tone(text)` — returns the emotional/tonal component only:
- `"crisis"` — crisis language detected
- `"emotional"` — sub-crisis distress
- `"frustrated"` — frustration with the system
- `"confused"` — overwhelmed/lost
- `"neutral"` — no strong emotional signal

This replaces the dual-purpose `_classify_message()` for emotional categories. The action categories (reset, greeting, thanks, confirm_yes, confirm_deny, etc.) stay as-is — they're about user intent, not tone.

### Phase 3 — Unified routing in generate_reply()

```python
def generate_reply(message, session_id, ...):
    # 1. PII redaction (unchanged)
    redacted_message, pii_detections = redact_pii(message)
    
    # 2. Always extract slots first
    extracted = extract_slots(message)  # or extract_slots_smart()
    has_service_intent = extracted.get("service_type") is not None
    additional_services = extracted.pop("additional_services", [])
    
    # 3. Classify action intent (reset, greeting, confirm, etc.)
    action = _classify_action(message)
    
    # 4. Classify emotional tone
    tone = _classify_tone(message)
    
    # 5. Crisis always wins — regardless of slots
    if tone == "crisis":
        # handle crisis (unchanged)
        return crisis_response
    
    # 6. Action intents that don't involve services
    if action in ("reset", "greeting", "thanks", "bot_identity", "bot_question"):
        # handle as today (unchanged)
        return action_response
    
    # 7. Confirmation actions (context-dependent)
    if action in ("confirm_yes", "confirm_deny", "confirm_change_service", 
                   "confirm_change_location"):
        # handle confirmation (unchanged)
        return confirmation_response
    
    # 8. THE KEY CHANGE: service intent + tone combined
    if has_service_intent:
        # Queue additional services
        if additional_services:
            existing["_queued_services"] = additional_services
        
        # Merge slots, proceed to confirmation/follow-up
        merged = merge_slots(existing, extracted)
        
        # Frame the response with the appropriate tone
        if tone == "emotional":
            # Acknowledge feelings, then proceed to service
            prefix = "I hear you, and I want to help. "
        elif tone == "frustrated":
            # Acknowledge frustration, then proceed to new search
            prefix = "I understand this has been frustrating. Let me try something different. "
        elif tone == "confused":
            prefix = "No worries — let me help you with that. "
        else:
            prefix = ""
        
        # Normal service flow continues with prefix applied...
        if is_enough_to_answer(merged):
            confirm_msg = prefix + _build_confirmation_message(merged)
            # ... confirmation flow
        else:
            follow_up = prefix + next_follow_up_question(merged)
            # ... follow-up flow
    
    # 9. No service intent — handle by tone alone
    if tone == "emotional":
        # pure emotional response (unchanged)
    if tone == "frustrated":
        # pure frustration response (unchanged)  
    if tone == "confused":
        # pure confused response (unchanged)
    
    # 10. Escalation, general conversation (unchanged)
```

### Phase 4 — Service queue handling

After delivering results for the first service, check `_queued_services`:

```python
# After results are shown:
queued = existing.get("_queued_services", [])
if queued:
    next_service, next_detail = queued.pop(0)
    existing["_queued_services"] = queued
    save_session_slots(session_id, existing)
    
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

### Phase 5 — LLM extractor updates (llm_slot_extractor.py)

Update the tool schema to support multiple service types:

```python
"service_type": {
    "type": "array",
    "items": {
        "type": "string",
        "enum": ["food", "shelter", ...],
    },
    "description": "All service types the user is looking for. "
                   "May be multiple (e.g., 'food and shelter').",
}
```

Or simpler: add a second field:
```python
"additional_service_types": {
    "type": "array",
    "items": {"type": "string", "enum": [...]},
    "description": "Any additional service types beyond the primary one."
}
```

## What Changes

| Component | Change | Risk |
|---|---|---|
| `_extract_service_type` | Returns list instead of first match | Low — internal function |
| `extract_slots` | Adds `additional_services` field | Low — callers ignore unknown keys |
| `_classify_message` | Split into `_classify_action` + `_classify_tone` | Medium — core routing logic |
| `generate_reply` | Reorder: extract → classify → route by both | Medium — lots of branches |
| `_execute_and_respond` | Add queue check after results | Low — additive |
| LLM extractor schema | Support array service_type | Low — schema change only |
| `_has_service_words` | Removed entirely | Low — no longer needed |
| help/escalation guards | Removed entirely | Low — no longer needed |

## What Doesn't Change

- `query_services`, `execute_service_query`, templates — still single-service
- `ChatResponse` model — no schema change
- Frontend — no changes needed
- Crisis detection — still highest priority
- Confirmation flow — still one service at a time
- PII redaction — unchanged

## Migration Strategy

1. **PR 1: Extract all service types** — `_extract_all_service_types`, `extract_slots` returns `additional_services`, add tests. No routing changes yet.
2. **PR 2: Split classifier** — `_classify_action` + `_classify_tone`, remove `_has_service_words` and ad-hoc guards. Route by combination. Add tests.
3. **PR 3: Service queue** — Store `_queued_services`, offer next service after results. Add tests.
4. **PR 4: LLM extractor** — Update schema for multi-service. Add tests.

## Test Scenarios

```
"I need food and shelter in Brooklyn"
  → primary: food, queued: [shelter], location: Brooklyn
  → confirms food → results → "You also mentioned shelter..."

"I'm really struggling, I need food and somewhere to sleep in Queens"
  → primary: food, queued: [shelter], location: Queens, tone: emotional
  → "I hear you. I'll search for food in Queens, with shelter queued"

"That wasn't helpful. Find me clothing in the Bronx instead"
  → primary: clothing, location: Bronx, tone: frustrated
  → "I understand. I'll search for clothing in the Bronx."

"I don't know what I need... maybe food?"
  → primary: food, tone: confused
  → "No worries — I can search for food. What neighborhood are you in?"

"I need food and dental care and legal help in Manhattan"
  → primary: food, queued: [medical/dental, legal], location: Manhattan
  → food first → dental next → legal last
```
