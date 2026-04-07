# PII Redaction

This document describes how the YourPeer chatbot detects and redacts personally identifiable information, the tradeoffs behind each pattern, known gaps, and directions for future improvement.

## Overview

PII redaction runs on every incoming user message and on bot responses before they are stored in the session transcript or audit log. The original (unredacted) user text is still used for slot extraction so that location names and ages parse correctly, but the redacted version is all that persists.

The confirmation echo ("I'll search for food in Brooklyn") also runs through the redactor so that PII accidentally captured in a slot value (e.g. a street address extracted as a location) is never displayed back to the user.

## Design Principles

**Regex-only, no heavy dependencies.** The redactor uses compiled regular expressions with no external libraries (no spaCy, no Presidio). This keeps the deploy simple and fast (<1ms per message).

**Precision over recall.** Each pattern is tuned to minimize false positives. In a chatbot where most messages are short service requests like "I need food in Brooklyn", a false positive is more disruptive than a missed detection — redacting "Brooklyn" as a name or "17" as part of a phone number would break the conversation. Where a pattern has ambiguity, we err on the side of not redacting.

**Overlap resolution.** Detections are checked against all prior matches before being added. If a span was already matched (e.g. a 9-digit number as SSN), it won't also be matched as a phone number. SSN is checked before phone because SSNs are a strict subset of the phone digit range.

**Detection order.** Patterns run in a fixed order — SSN, email, phone, DOB, address, name — with each stage skipping spans already claimed by earlier stages. This prevents double-counting and ensures the most specific match wins.

## Categories

| PII Type | Placeholder | Example Input | Example Output |
|---|---|---|---|
| Phone number | `[PHONE]` | `Call me at 212-555-1234` | `Call me at [PHONE]` |
| Social Security # | `[SSN]` | `My SSN is 123-45-6789` | `My SSN is [SSN]` |
| Email address | `[EMAIL]` | `Email me at user@test.com` | `Email me at [EMAIL]` |
| Date of birth | `[DOB]` | `Born 01/15/1990` | `Born [DOB]` |
| Street address | `[ADDRESS]` | `I live at 123 Main Street Apt 4B` | `I live at [ADDRESS]` |
| Name | `[NAME]` | `My name is Sarah` | `My name is [NAME]` |

## Pattern Details and Tradeoffs

### Phone Numbers

**Pattern:** Optional country code (`+1`), 3-digit area code (with or without parens), 3+4 digit subscriber number. Separators can be spaces, dashes, or dots. Requires 10-11 total digits.

**Catches:** `(212) 555-1234`, `212-555-1234`, `212.555.1234`, `2125551234`, `+1 212 555 1234`

**Tradeoff — 10-digit numeric IDs.** Any 10-digit number will match, including case numbers, benefit IDs, or reference codes a user might share. There is no way to distinguish these from phone numbers using regex alone. The 10-11 digit filter prevents shorter numbers (zip codes, ages, counts) from matching, but genuine 10-digit non-phone IDs will be over-redacted.

### Social Security Numbers

**Pattern:** Three groups in 3-2-4 digit structure, with optional dash or space separators.

**Catches:** `123-45-6789`, `123 45 6789`, `123456789`

**Tradeoff — any 3-2-4 digit grouping.** A case number or reference ID formatted as `XXX-XX-XXXX` will be flagged as an SSN. The grouping structure is the only distinguishing signal available to regex. SSN is checked before phone so that 9-digit matches are claimed as SSN rather than being misclassified as a short phone number.

### Email Addresses

**Pattern:** Standard `user@domain.tld` format.

**Catches:** `sarah@gmail.com`, `user.name+tag@example.co.uk`

**No significant tradeoffs.** Email format is distinctive enough that false positives are extremely rare in conversational text.

### Dates of Birth

**Pattern:** Two formats: numeric `MM/DD/YYYY` (or `M/D/YY`, with `/` or `-`) and written-out `January 15, 1990` (or `Jan 15 1990`).

**Catches:** `01/15/1990`, `1/15/90`, `01-15-1990`, `January 15, 1990`, `Jan 15 1990`

**Tradeoff — any date matches, not just birthdays.** The pattern has no context check for "born", "birthday", "DOB", etc. Any date in `MM/DD/YYYY` format will be redacted, including appointment dates, document dates, or references like "come back on 4/15/2026". This is a deliberate precision tradeoff: requiring a "birthday" keyword would miss most real DOB disclosures ("I was born 01/15/1990" doesn't always include the keyword), and over-redacting dates is less harmful than leaking a real DOB.

### Street Addresses

**Patterns:** Four complementary patterns, all requiring a leading house number:

1. **Standard:** `number + word name(s) + suffix` — e.g. "123 Main Street", "456 West Oak Avenue"
2. **Ordinal:** `number + optional direction + ordinal + suffix` — e.g. "789 5th Avenue", "456 West 42nd Street"
3. **Broadway:** `number + Broadway` — special case, no suffix needed
4. **Suffix-less with preposition:** `at/on/to + number + word(s)` — e.g. "I live at 123 Main"

All four patterns optionally capture a trailing apartment/unit identifier (`Apt 4B`, `#12`, `Unit 3`, `Suite 5A`, `Fl 2`, `Rm 8`).

**Street suffixes recognized:** Street, St, St., Avenue, Ave, Boulevard, Blvd, Road, Rd, Drive, Dr, Lane, Ln, Place, Pl, Court, Ct, Way, Terrace, Ter, Ter.

**Tradeoff — `St` and `Ter` abbreviations.** These were initially excluded because they collide with common words ("status", "still", "shelter", "terminal"). They are now included because the full pattern requires a leading house number + capitalized word before the suffix, which eliminates those false positives. The word "St" in isolation will never match — only "123 Main St" will.

**Tradeoff — suffix-less addresses require a preposition.** "I live at 123 Main" is detected, but bare "123 Main" is not. Without the preposition constraint, any `number + word` combination would match ("5 Borough", "2 Meals"), creating unacceptable false positives. This means a user who types just "123 Main" without a preposition will not be redacted.

**Gap — no PO Box detection.** "PO Box 1234" is not currently detected.

**Gap — no cross-street format.** "Corner of 5th and Main" or "5th and Lexington" are not detected.

### Names

**Pattern:** Heuristic matching based on common intro phrases: "my name is", "name's", "I'm", "call me", "this is" — followed by one or two capitalized words.

**Catches:** `My name is John Smith`, `I'm Sarah`, `Call me David`, `This is Maria`

**Tradeoff — requires an intro phrase.** A name mentioned without an intro ("Sarah needs food in Brooklyn") will not be detected. This is intentional: without an intro phrase, there is no way to distinguish a name from a place name, service keyword, or any other capitalized word using regex alone.

**Tradeoff — manually maintained blocklist.** The `I'm` pattern is the most aggressive — "I'm Sarah" should match, but "I'm in Brooklyn" and "I'm hungry" should not. A blocklist of ~60 words prevents false positives on NYC boroughs, neighborhoods, service keywords, common adjectives, and prepositions. If a new neighborhood or keyword is added to the system, the blocklist must be updated manually, or users typing "I'm [NewNeighborhood]" will see a false NAME detection.

**Gap — single-word names only for `I'm` pattern.** "I'm Sarah Johnson" will only capture "Sarah", not "Sarah Johnson". The other intro patterns ("my name is", "call me") capture up to two words.

## Where Redaction Runs

| Location | What Gets Redacted | Why |
|---|---|---|
| `chatbot.generate_reply()` | Every incoming user message | Redacted version stored in session transcript and audit log |
| `chatbot._log_turn()` | Bot response before audit log storage | Prevents PII echoed by the LLM (e.g. "Hi Bryan!") from persisting in transcripts |
| `chatbot._build_confirmation_message()` | Slot values echoed in confirmation | Prevents PII captured in location slot from being displayed back |

Slot extraction runs on the **original** (unredacted) text so that locations and ages still parse. Only redacted versions of both user messages and bot responses are stored.

## Code Location

All detection logic and response text lives in a single file:

```
backend/app/privacy/pii_redactor.py
```

Key functions:
- `detect_pii(text)` — returns a list of `PIIDetection` objects without modifying the text
- `redact_pii(text)` — returns `(redacted_text, detections)` with placeholders substituted
- `has_pii(text)` — quick boolean check

## Test Coverage

```bash
pytest tests/test_pii_redactor.py -v     # 15 tests covering all categories
pytest tests/test_edge_cases.py -v        # PII + slot interaction tests
```

Tests cover:
- Each PII type with multiple format variations
- False positive checks on NYC locations and service keywords
- Apartment/unit capture with addresses
- Abbreviated street suffixes (St, Ter)
- Suffix-less addresses with preposition context
- PII not leaking through confirmation echo
- PII redaction not breaking slot extraction

## Future Improvements

**Context-aware DOB detection.** Add optional keyword proximity check ("born", "birthday", "DOB", "date of birth") within N words of the date pattern. This would reduce false positives on non-birthday dates while still catching most real disclosures. Start with both modes (strict keyword-required + current catch-all) and compare false positive rates before switching.

**PO Box and cross-street detection.** Add patterns for "PO Box NNNN" and "corner of X and Y" / "X and Y" where both X and Y match known street names or suffixes.

**Name detection beyond intro phrases.** The current approach is limited to names preceded by "my name is", "I'm", etc. An NER model (even a lightweight one) would catch names in other positions. However, this conflicts with the no-heavy-dependencies principle. A middle ground: expand the intro phrase list to cover more patterns ("they call me", "everyone calls me", "you can call me") and add a "sign-off" pattern ("Thanks, Sarah" / "— John").

**Confidence scoring.** Return a confidence level with each detection so downstream consumers can make threshold decisions. SSN and email patterns are near-certain; the `I'm` name pattern and suffix-less address pattern are lower confidence. The confirmation echo could redact only high-confidence detections while the audit log redacts everything.

**LLM-assisted PII detection.** For messages where regex returns nothing but the text is long and conversational, an LLM pass could catch PII the regex missed — similar to the two-stage approach used for crisis detection and slot extraction. This would only run on messages that pass through the LLM for other reasons (slot extraction or conversational fallback), adding no extra latency.
