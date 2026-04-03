# YourPeer Chatbot — Success Metrics

This document defines the metrics used to evaluate the YourPeer chatbot, organized by layer. Each metric includes a definition, a concrete target, the measurement method, and whether it applies to the pilot phase or post-pilot production.

Metrics are grouped into five layers: **Intake Quality**, **Answer Quality**, **Safety**, **System Quality** (automated eval), and **Closed-Loop Outcomes**. The first four are measurable from day one of the pilot. Closed-loop outcomes require additional infrastructure and are scoped to post-pilot.

---

## 1. Intake Quality

These metrics assess how well the chatbot collects the structured fields it needs to run a query.

### 1.1 Task Completion Rate
**Definition:** % of sessions that reach a confirmed database query (i.e. user taps "Yes, search" or equivalent) out of all sessions that express a service need.  
**Target:** ≥ 70% at pilot launch → ≥ 80% at end of pilot.  
**Measurement:** Audit log — count sessions with a `query_execution` event divided by sessions with a detected service intent.  
**Phase:** Pilot.

### 1.2 Slot Confirmation Rate
**Definition:** % of required slots (service type, location) that are confirmed by the user rather than assumed or skipped.  
**Target:** ≥ 90%.  
**Measurement:** Audit log — compare `slots_filled` vs. `slots_confirmed` fields in conversation turn events.  
**Phase:** Pilot.

### 1.3 Slot Correction Rate
**Definition:** % of sessions where the user corrects a slot after the confirmation step (e.g. taps "Change location" or "Change service").  
**Why it matters:** High correction rates signal misextraction or confirmation UX problems.  
**Target:** ≤ 15%.  
**Measurement:** Audit log — count sessions with a slot-change event after the first confirmation message.  
**Phase:** Pilot.

### 1.4 Confirmation Action Breakdown
**Definition:** Distribution of user actions at the confirmation step: confirm / change location / change service / start over / abandon.  
**Target:** ≥ 65% confirm on first presentation; abandon ≤ 10%.  
**Measurement:** Audit log — tag each confirmation response with one of the five action types.  
**Phase:** Pilot.

### 1.5 Turns to Confirmation
**Definition:** Average number of conversation turns from session start to the confirmation step.  
**Target:** ≤ 3 turns for users who tap quick-reply buttons; ≤ 5 turns for free-text users.  
**Measurement:** Audit log — count turns per session up to the first `confirmation_shown` event.  
**Phase:** Pilot.

### 1.6 Session Abandonment Rate
**Definition:** % of sessions that end without reaching a query execution.  
**Target:** ≤ 30% overall; ≤ 20% for sessions that get past the first bot message.  
**Measurement:** Audit log — sessions with no `query_execution` event and last activity > 10 minutes ago.  
**Phase:** Pilot.

---

## 2. Answer Quality

These metrics assess the quality and usefulness of search results returned to the user.

### 2.1 No-Result Rate
**Definition:** % of executed queries that return zero matching services, after relaxed fallback is applied.  
**Target:** ≤ 15% overall; ≤ 10% for food and shelter (highest-demand categories).  
**Measurement:** Audit log — `query_execution` events where `result_count = 0` after fallback.  
**Phase:** Pilot.

### 2.2 Relaxed Query Rate
**Definition:** % of queries that only return results after filters are relaxed (strict query returned zero).  
**Why it matters:** High rates signal that strict eligibility rules in query templates may be too narrow for the actual database coverage.  
**Target:** ≤ 25%. Investigate if consistently above 30% for any category.  
**Measurement:** Audit log — `query_execution` events flagged `relaxed=true`.  
**Phase:** Pilot.

### 2.3 Data Freshness Rate
**Definition:** % of returned service cards where the `last_verified` date is within the past 90 days.  
**Target:** ≥ 80% of cards served are verified within 90 days.  
**Measurement:** Query result metadata — check `last_verified` field on each returned service record.  
**Phase:** Pilot.

### 2.4 Eligibility Fit Rate
**Definition:** % of returned services that match all stated user criteria (service type, age restrictions, gender restrictions, location).  
**Target:** ≥ 95% — the template query design should make mismatches rare; any miss is a template bug.  
**Measurement:** Canary tests (scripted dialogs with known-correct results) run before each deploy. Spot-check by data stewards during pilot.  
**Phase:** Pilot.

### 2.5 User Feedback Score
**Definition:** % of post-result feedback that is positive (thumbs up or equivalent), when feedback is collected.  
**Target:** ≥ 70% positive at pilot launch.  
**Measurement:** In-chat feedback prompt after results are shown (to be implemented post-MVP).  
**Phase:** Post-pilot MVP.

---

## 3. Safety

These metrics assess how the system handles crisis situations and sensitive content.

### 3.1 Crisis Detection Rate
**Definition:** % of sessions containing crisis language (self-harm, violence, DV, trafficking, medical emergency) that trigger the crisis response path.  
**Target:** 100% — no crisis message should be silently dropped.  
**Measurement:** Audit log — `crisis_detected` events; cross-check by manually reviewing a sample of sessions flagged by keyword search on stored transcripts.  
**Phase:** Pilot.

### 3.2 Crisis False Positive Rate
**Definition:** % of sessions where crisis detection fires incorrectly on non-crisis content.  
**Why it matters:** False positives disrupt the flow for non-crisis users and erode trust.  
**Target:** ≤ 5%.  
**Measurement:** Manual review of a random sample of `crisis_detected` sessions by data steward.  
**Phase:** Pilot.

### 3.3 Escalation Rate
**Definition:** % of sessions where the user requests a human peer navigator.  
**Why it matters:** A very high escalation rate may indicate the bot isn't resolving common needs; very low may mean users don't know the option exists.  
**Target:** Track as a baseline in pilot; no hard target until patterns emerge.  
**Measurement:** Audit log — sessions with an `escalation_requested` event.  
**Phase:** Pilot.

### 3.4 PII Leakage Rate
**Definition:** % of stored conversation transcripts that contain detectable PII after redaction (names, phone numbers, SSNs, email addresses, street addresses).  
**Target:** 0% detectable PII in stored transcripts.  
**Measurement:** Automated PII scanner (regex + NER) run on transcript sample weekly during pilot. Manual spot-check monthly.  
**Phase:** Pilot.

### 3.5 Hallucination Rate
**Definition:** % of bot responses that contain fabricated service information (names, addresses, hours, phone numbers, eligibility rules not sourced from the database).  
**Target:** < 1%. The architecture makes this structurally near-impossible (all service data is DB-sourced), but canary tests and human review confirm it.  
**Measurement:** Canary test suite (scripted dialogs verified against known DB output) run on every deploy. Manual review of a random sample of `query_execution` sessions during pilot.  
**Phase:** Pilot.

---

## 4. System Quality (LLM-as-Judge Eval)

These metrics come from the automated evaluation framework in `tests/eval_llm_judge.py`, which runs scripted and simulated conversations through the full system and scores them using Claude as an impartial judge.

The eval covers 29 scenarios across 8 scoring dimensions, each rated 1–5. It can be triggered from the admin console (Eval tab → Run Evals) or via CLI.

### Dimensions and Targets

| Dimension | Definition | Pilot Target |
|---|---|---|
| Slot Extraction Accuracy | Correctly identifies service type, location, age, urgency | ≥ 4.0 / 5.0 |
| Dialog Efficiency | Reaches result in minimal, well-targeted turns | ≥ 3.5 / 5.0 |
| Response Tone | Warm, respectful, trauma-informed, non-judgmental | ≥ 4.0 / 5.0 |
| Safety & Crisis Handling | Crisis language triggers correct resources immediately | ≥ 4.5 / 5.0 |
| Confirmation UX | Confirmation step is clear; changes handled correctly | ≥ 3.5 / 5.0 |
| Privacy | No PII echoed back; redaction works correctly | ≥ 4.5 / 5.0 |
| Hallucination Resistance | No fabricated service data in any response | ≥ 4.5 / 5.0 |
| Error Recovery | Graceful handling of no results, ambiguous input, DB failures | ≥ 3.5 / 5.0 |

**Overall average target:** ≥ 4.0 / 5.0.  
**Critical failures:** 0 (any score of 1 on Safety & Crisis Handling or Hallucination Resistance is a deploy blocker).

### Cadence
- Run the full 29-scenario eval before each significant deploy.
- Run the 5-scenario "quick" eval (happy path + crisis) before minor deploys or hotfixes.
- Store results in `tests/eval_report.json`; view in admin console.

---

## 5. Closed-Loop Outcomes

These metrics answer the ultimate question: did the referral work? They require additional infrastructure beyond the pilot and are flagged accordingly.

### 5.1 Referral Success Rate
**Definition:** % of query sessions where the user subsequently confirms they visited or contacted the referred service.  
**Target:** ≥ 75% of users who receive results and opt into follow-up confirm contact with the service.  
**Measurement:** Requires SMS follow-up flow — send a check-in message 24–48 hours after a confirmed referral ("Did you make it to [service name]?"). **Not implemented in pilot.**  
**Phase:** Post-pilot.

### 5.2 Service Accuracy Rate (Post-Visit)
**Definition:** % of post-visit feedback responses where the service details shown (hours, address, eligibility) matched what the user found on arrival.  
**Target:** ≥ 85%.  
**Measurement:** Post-visit feedback SMS prompt ("Was the information we gave you accurate?"). **Not implemented in pilot.**  
**Phase:** Post-pilot.

### 5.3 Outcome Linkage
**Definition:** Ability to correlate referral success rates with user profile attributes (borough, service type, session length, device type) to identify patterns.  
**Why it matters:** The architecture doc identifies this as the "ultimate goal" — using outcome data to improve query templates and surface quality data back to partner organizations.  
**Measurement:** Requires linking anonymized session IDs to follow-up responses without storing PII. Needs privacy review before implementation.  
**Phase:** Post-pilot. Requires privacy design work.

---

## Metric Collection Infrastructure

| Source | What It Captures | Available Now? |
|---|---|---|
| Audit log (in-memory) | All session events, slots, query results, crisis flags | ✅ Yes |
| Admin console | Aggregated stats, conversation transcripts, query log, eval results | ✅ Yes |
| Canary test suite | Eligibility fit, hallucination, template correctness | ✅ Yes (run manually or on deploy) |
| LLM-as-judge eval | 8-dimension automated quality scoring | ✅ Yes (admin console or CLI) |
| PII scanner | Automated redaction verification | ⚠️ Partial (regex-based; NER not yet integrated) |
| SMS follow-up | Referral success, post-visit accuracy | ❌ Not implemented |
| In-chat feedback | User satisfaction after results | ❌ Not implemented |

---

## Pilot Review Cadence

- **Weekly:** Data steward reviews admin console — no-result rate, crisis events, abandonment rate, any PII scanner alerts.
- **Per deploy:** Run full LLM-as-judge eval; confirm 0 critical failures and overall ≥ 4.0 before promoting to production.
- **Monthly:** Manual spot-check of 20–30 conversation transcripts for tone, accuracy, and edge case handling.
- **End of pilot:** Compile all metrics against targets; decide which closed-loop infrastructure to build for Phase 2.
