// Copyright (c) 2024 Streetlives, Inc.
// Use of this source code is governed by an MIT-style license.

/**
 * Metric definitions for the detail dialog. Each entry maps a metric
 * key (matching the MetricRow `name` prop) to its definition, formula,
 * target rationale, and source section in METRICS.md.
 */

export interface MetricDefinition {
  name: string;
  section: string;
  definition: string;
  formula: string;
  target: string;
  rationale: string;
  phase: "Pilot" | "Post-pilot";
}

// Key: the exact MetricRow `name` string used in metrics/page.tsx
export const METRIC_DEFINITIONS: Record<string, MetricDefinition> = {
  // --- 1. Intake Quality ---
  "Task Completion Rate": {
    name: "Task Completion Rate",
    section: "1.1",
    definition: "% of sessions that reach a confirmed database query out of all sessions that express a service need.",
    formula: "sessions with query_execution / service-intent sessions (service, confirmation, or confirm_* turns). Greeting-only, help, and crisis-only sessions are excluded.",
    target: "≥ 70% at pilot launch → ≥ 80% at end of pilot",
    rationale: "Measures whether the conversational intake flow is successfully guiding users through to a search result. Low completion signals friction in the intake or confirmation steps.",
    phase: "Pilot",
  },
  "Slot Confirmation Rate": {
    name: "Slot Confirmation Rate",
    section: "1.2",
    definition: "% of queries that went through the explicit confirmation step (user tapped 'Yes, search') before executing.",
    formula: "sessions with both confirm_yes and query_execution / sessions with query_execution",
    target: "≥ 90%",
    rationale: "Should be ~100% by design. Any gap means the confirmation flow was bypassed and a query ran without user approval — investigate immediately.",
    phase: "Pilot",
  },
  "Slot Correction Rate": {
    name: "Slot Correction Rate",
    section: "1.3",
    definition: "% of sessions where the user corrects a slot after the confirmation step (e.g. 'Change location' or 'Change service').",
    formula: "sessions with confirm_change_* / sessions that reached confirmation",
    target: "≤ 15%",
    rationale: "High correction rates signal misextraction or confusing confirmation UX. The slot extractor or follow-up questions may need tuning.",
    phase: "Pilot",
  },
  "Confirm Rate": {
    name: "Confirm Rate",
    section: "1.4",
    definition: "% of confirmation actions that are 'Yes, search' (confirm) vs change or deny.",
    formula: "confirm_yes / total confirmation actions (confirm + change_location + change_service + deny)",
    target: "≥ 65% on first presentation",
    rationale: "Measures how often the chatbot gets the right slots on the first try. Low rates mean the slot extractor is frequently wrong.",
    phase: "Pilot",
  },
  "Confirmation: Confirm Rate": {
    name: "Confirmation: Confirm Rate",
    section: "1.4",
    definition: "% of confirmation actions that are 'Yes, search' (confirm) vs change or deny.",
    formula: "confirm_yes / total confirmation actions (confirm + change_location + change_service + deny)",
    target: "≥ 65% on first presentation",
    rationale: "Measures how often the chatbot gets the right slots on the first try. Low rates mean the slot extractor is frequently wrong.",
    phase: "Pilot",
  },
  "Abandon Rate": {
    name: "Abandon Rate",
    section: "1.4",
    definition: "% of sessions that reach confirmation but never confirm (user leaves or denies without re-engaging).",
    formula: "sessions at confirmation without confirm_yes / sessions at confirmation",
    target: "≤ 10%",
    rationale: "High abandonment at the confirmation step suggests the proposed search doesn't match what the user actually needs.",
    phase: "Pilot",
  },
  "Confirmation: Abandon Rate": {
    name: "Confirmation: Abandon Rate",
    section: "1.4",
    definition: "% of sessions that reach confirmation but never confirm (user leaves or denies without re-engaging).",
    formula: "sessions at confirmation without confirm_yes / sessions at confirmation",
    target: "≤ 10%",
    rationale: "High abandonment at the confirmation step suggests the proposed search doesn't match what the user actually needs.",
    phase: "Pilot",
  },
  // --- 2. Answer Quality ---
  "Relaxed Query Rate": {
    name: "Relaxed Query Rate",
    section: "2.2",
    definition: "% of queries that only return results after filters are relaxed (strict query returned zero).",
    formula: "query_execution events with relaxed=true / total query_execution events",
    target: "≤ 25%",
    rationale: "High rates signal that strict eligibility rules in query templates may be too narrow for the actual database coverage. Investigate if consistently above 30% for any category.",
    phase: "Pilot",
  },
  "Data Freshness": {
    name: "Data Freshness",
    section: "2.3",
    definition: "% of returned service cards where the last_validated_at date is within the past 90 days.",
    formula: "cards with last_validated_at within 90 days / total cards served",
    target: "≥ 80%",
    rationale: "Stale data erodes trust. If a user visits a service and finds it closed or moved, the chatbot has failed even though it returned a 'result.'",
    phase: "Pilot",
  },
  "Data Freshness Rate": {
    name: "Data Freshness Rate",
    section: "2.3",
    definition: "% of returned service cards where the last_validated_at date is within the past 90 days.",
    formula: "cards with last_validated_at within 90 days / total cards served",
    target: "≥ 80%",
    rationale: "Stale data erodes trust. If a user visits a service and finds it closed or moved, the chatbot has failed even though it returned a 'result.'",
    phase: "Pilot",
  },
  "User Feedback Score": {
    name: "User Feedback Score",
    section: "2.6",
    definition: "% of post-result feedback that is positive (thumbs up).",
    formula: "feedback_up / (feedback_up + feedback_down)",
    target: "≥ 70%",
    rationale: "Direct user signal on whether the results were useful. The in-chat thumbs up/down prompt appears after service results are delivered.",
    phase: "Pilot",
  },
  // --- 3. Safety ---
  "Crisis Detection Rate": {
    name: "Crisis Detection Rate",
    section: "3.1",
    definition: "% of sessions containing crisis language that trigger the crisis response path.",
    formula: "crisis_detected events / sessions with crisis language (manual review baseline)",
    target: "100% — no crisis message should be silently dropped",
    rationale: "This is a safety-critical metric. The two-stage detection (regex + LLM) is designed to catch both explicit and indirect crisis language. Any miss could leave a vulnerable person without resources.",
    phase: "Pilot",
  },
  "Crisis Detection Count": {
    name: "Crisis Detection Count",
    section: "3.1",
    definition: "Total number of sessions where crisis detection triggered. Should be 100% of sessions containing crisis language.",
    formula: "crisis_detected events in audit log",
    target: "100% of crisis messages caught",
    rationale: "This is a safety-critical metric. The two-stage detection (regex + LLM) is designed to catch both explicit and indirect crisis language. Any miss could leave a vulnerable person without resources.",
    phase: "Pilot",
  },
  "Escalation Rate": {
    name: "Escalation Rate",
    section: "3.3",
    definition: "% of sessions where the user requests a human peer navigator.",
    formula: "unique sessions with escalation category / total sessions",
    target: "Baseline tracking",
    rationale: "A very high rate may mean the bot isn't resolving common needs. Very low may mean users don't know the option exists. Track to establish baseline.",
    phase: "Pilot",
  },
  // --- 4. Conversation Quality ---
  "Emotional Detection Rate": {
    name: "Emotional Detection Rate",
    section: "4.1",
    definition: "% of sessions with at least one turn classified as emotional.",
    formula: "sessions with emotional category / total sessions",
    target: "Baseline tracking",
    rationale: "Near 0% likely means detection is too narrow for this population. Very high may mean phrase lists are too broad. Expect 10-25% for the homeless population.",
    phase: "Pilot",
  },
  "Emotional → Escalation Rate": {
    name: "Emotional → Escalation Rate",
    section: "4.2",
    definition: "Of sessions with an emotional turn, what % subsequently asked for a peer navigator?",
    formula: "sessions with both emotional and escalation / sessions with emotional",
    target: "Baseline tracking",
    rationale: "Measures whether the peer navigator offer in the emotional response is resonating. A healthy rate suggests users are engaging with the offer.",
    phase: "Pilot",
  },
  "Emotional → Service Rate": {
    name: "Emotional → Service Rate",
    section: "4.3",
    definition: "Of sessions with an emotional turn, what % eventually reached a service search?",
    formula: "sessions with emotional AND (service or query_execution) / sessions with emotional",
    target: "Baseline tracking",
    rationale: "Shows whether users who share something emotional find their way to practical help without being pushed there.",
    phase: "Pilot",
  },
  "Bot Question Rate": {
    name: "Bot Question Rate",
    section: "4.4",
    definition: "% of turns classified as bot_question (questions about the bot's capabilities).",
    formula: "bot_question turns / total turns",
    target: "Baseline tracking",
    rationale: "A spike may indicate users are confused about what the bot does — which could indicate an onboarding or UX problem.",
    phase: "Pilot",
  },
  "Bot Q → Frustration Rate": {
    name: "Bot Q → Frustration Rate",
    section: "4.5",
    definition: "Of sessions with a bot_question turn, what % subsequently had a frustration turn?",
    formula: "sessions with both bot_question and frustration / sessions with bot_question",
    target: "≤ 10%",
    rationale: "If users ask how the bot works and then get frustrated, the bot question answers aren't helpful enough.",
    phase: "Pilot",
  },
  "Bot Question → Frustration Rate": {
    name: "Bot Question → Frustration Rate",
    section: "4.5",
    definition: "Of sessions with a bot_question turn, what % subsequently had a frustration turn?",
    formula: "sessions with both bot_question and frustration / sessions with bot_question",
    target: "≤ 10%",
    rationale: "If users ask how the bot works and then get frustrated, the bot question answers aren't helpful enough.",
    phase: "Pilot",
  },
  "Conversational Discovery Rate": {
    name: "Conversational Discovery Rate",
    section: "4.6",
    definition: "Of sessions that reached a query execution, what % included a conversational turn before or alongside their service search?",
    formula: "query sessions with greeting/emotional/confused/general/bot_question / all query sessions",
    target: "Baseline tracking",
    rationale: "Measures whether users can find services through natural conversation, not just by tapping welcome menu buttons.",
    phase: "Pilot",
  },
  "⚠ General (LLM-Generated)": {
    name: "General (LLM-Generated)",
    section: "4.8",
    definition: "% of turns routed to the general category, where the LLM generates a free-form response not grounded in a query template or deterministic handler.",
    formula: "general category turns / total categorized turns",
    target: "≤ 15%",
    rationale: "This is the only path where the bot's response is not structurally constrained. Highest risk for hallucination, off-topic, or inappropriate content. Investigate if rising.",
    phase: "Pilot",
  },
  // --- Additional metrics ---
  "Avg Turns to Query": {
    name: "Avg Turns to Query",
    section: "1.5",
    definition: "Average number of conversation turns from session start to the first confirmed query execution.",
    formula: "sum of turns per completed session / number of completed sessions",
    target: "≤ 3 turns for quick-reply users; ≤ 5 for free-text users",
    rationale: "Fewer turns means faster time-to-value. If this rises, the intake flow may be asking too many follow-up questions or users may be struggling with the confirmation step.",
    phase: "Pilot",
  },
  "Session Abandonment Rate": {
    name: "Session Abandonment Rate",
    section: "1.6",
    definition: "% of sessions that end without reaching a query execution.",
    formula: "sessions with no query_execution / total sessions",
    target: "≤ 30% overall; ≤ 20% past first bot message",
    rationale: "High abandonment suggests users are leaving before getting results. Could indicate UX friction, confusing prompts, or unmet expectations about what the bot can do.",
    phase: "Pilot",
  },
  "No-Result Rate": {
    name: "No-Result Rate",
    section: "2.1",
    definition: "% of executed queries that return zero matching services, after relaxed fallback is applied.",
    formula: "query_execution events with result_count=0 (after fallback) / total queries",
    target: "≤ 15% overall; ≤ 10% for food and shelter",
    rationale: "No results means the user gets nothing useful. May indicate insufficient database coverage for the requested area or category, or overly strict eligibility filters.",
    phase: "Pilot",
  },
  "Eligibility Fit Rate": {
    name: "Eligibility Fit Rate",
    section: "2.5",
    definition: "% of returned services that match all stated user criteria (service type, age, gender, location).",
    formula: "Verified via canary tests — scripted dialogs with known-correct results",
    target: "≥ 95%",
    rationale: "The template query design should make mismatches rare. Any miss is a template bug — the SQL WHERE clause is wrong or the taxonomy mapping is incomplete.",
    phase: "Pilot",
  },
  "Crisis False Positive Rate": {
    name: "Crisis False Positive Rate",
    section: "3.2",
    definition: "% of sessions where crisis detection fires incorrectly on non-crisis content.",
    formula: "Manual review of a random sample of crisis_detected sessions by data steward",
    target: "≤ 5%",
    rationale: "False positives disrupt the flow for non-crisis users and erode trust. The emotional phrase guard was added specifically to reduce false positives on expressions like 'I'm feeling scared' that are emotional but not crisis.",
    phase: "Pilot",
  },
  "PII Leakage Rate": {
    name: "PII Leakage Rate",
    section: "3.4",
    definition: "% of stored conversation transcripts that contain detectable PII after redaction (names, phone numbers, SSNs, emails, addresses).",
    formula: "Automated PII scanner run on transcript sample weekly during pilot",
    target: "0%",
    rationale: "PII in stored transcripts is a privacy violation. The redactor runs on every message before storage. Any leak indicates a regex gap or a new PII pattern not covered.",
    phase: "Pilot",
  },
  "Hallucination Rate": {
    name: "Hallucination Rate",
    section: "3.5",
    definition: "% of bot responses that contain fabricated service information (names, addresses, hours, phone numbers, eligibility rules not from the database).",
    formula: "Canary tests + manual review of query_execution sessions",
    target: "< 1%",
    rationale: "The architecture makes this structurally near-impossible — all service data is DB-sourced, not LLM-generated. The post-results handler reinforces this by answering follow-up questions from stored card data, never from LLM generation.",
    phase: "Pilot",
  },
  "Queue Offers": {
    name: "Queue Offers",
    section: "4.10",
    definition: "Count of times the bot offered a second service after delivering results for a multi-intent message.",
    formula: "Sessions with queue_decline event + sessions with 2+ different query templates executed",
    target: "Baseline tracking",
    rationale: "Indicates how often the multi-service extraction is surfacing genuine needs. High volume with low accept rate may signal false extractions.",
    phase: "Pilot",
  },
  "Queue Declines": {
    name: "Queue Declines",
    section: "4.10",
    definition: "Count of times the user declined a queued service offer ('No thanks').",
    formula: "conversation_turn events with category 'queue_decline'",
    target: "Baseline tracking",
    rationale: "A high decline rate relative to offers may indicate the multi-service extractor is finding false positives — services the user didn't actually want.",
    phase: "Pilot",
  },
  "Queue Accept Rate": {
    name: "Queue Accept Rate",
    section: "4.10",
    definition: "% of queue offers that were accepted (user searched the next service).",
    formula: "(queue_offers - queue_declines) / queue_offers. Note: users who ignore the offer inflate the accept rate.",
    target: "Baseline tracking",
    rationale: "Measures whether multi-service detection is surfacing genuine needs. A healthy rate suggests users with complex situations are being well served.",
    phase: "Pilot",
  },
  "Referral Success Rate": {
    name: "Referral Success Rate",
    section: "6.1",
    definition: "% of query sessions where the user subsequently confirms they visited or contacted the referred service.",
    formula: "SMS follow-up confirmation / total referred sessions (opt-in only)",
    target: "≥ 75% of users who opt into follow-up",
    rationale: "The ultimate measure of whether the chatbot is actually helping. Requires SMS follow-up infrastructure not yet built.",
    phase: "Post-pilot",
  },
  "Service Accuracy Rate": {
    name: "Service Accuracy Rate",
    section: "6.2",
    definition: "% of post-visit feedback responses where the service details shown (hours, address, eligibility) matched what the user found on arrival.",
    formula: "Post-visit feedback confirming accuracy / total post-visit responses",
    target: "≥ 85%",
    rationale: "If users arrive to find different hours or a closed service, the data freshness problem is causing real harm. Directly measures database quality.",
    phase: "Post-pilot",
  },
  "Outcome Linkage": {
    name: "Outcome Linkage",
    section: "6.3",
    definition: "Correlate referral success rates with user profile characteristics and service locations to identify systematic gaps.",
    formula: "Statistical analysis of success rate × user demographics × service location",
    target: "Baseline established",
    rationale: "Helps identify if certain neighborhoods, service types, or user demographics have systematically lower success rates — enabling targeted data quality improvement.",
    phase: "Post-pilot",
  },
  // --- New P0-P3 metrics (Run 23+) ---
  "Bounce Rate": {
    name: "Bounce Rate",
    section: "P1.5",
    definition: "% of sessions with exactly 1 user turn (user sent one message and never came back).",
    formula: "sessions with 1 turn / total sessions",
    target: "≤ 25%",
    rationale: "High bounce rate suggests the welcome message or first response isn't engaging. Industry benchmark is 15-25%. Sessions where the bot fails to understand the first message have a 70% bounce rate (Calabrio).",
    phase: "Pilot",
  },
  "Correction Rate": {
    name: "Correction Rate",
    section: "P0.2",
    definition: "% of sessions where the user triggered the correction handler ('not what I meant').",
    formula: "sessions with correction category / total sessions",
    target: "≤ 5%",
    rationale: "Directly measures misclassification. Each correction means the bot misunderstood the user's intent. High rates signal that the regex classifier or LLM gate needs improvement.",
    phase: "Pilot",
  },
  "Negative Preference Rate": {
    name: "Negative Preference Rate",
    section: "P0.2",
    definition: "% of sessions where the user rejected all offered results.",
    formula: "sessions with negative_preference category / total sessions",
    target: "≤ 10%",
    rationale: "High rates signal poor search quality or mismatched service categories. The user found services but none were what they needed.",
    phase: "Pilot",
  },
  "Bot Repetition Rate": {
    name: "Bot Repetition Rate",
    section: "P2.12",
    definition: "% of sessions where the bot gives the exact same response text on two consecutive turns.",
    formula: "sessions with identical consecutive bot responses / total sessions",
    target: "≤ 5%",
    rationale: "The eval judge specifically flags repetition. Calabrio's Bot Experience Score includes repetition as a negative factor. Directly measures the frustration loop problem.",
    phase: "Pilot",
  },
};

/**
 * Look up a metric definition by name. Returns undefined if not found.
 * The lookup is case-insensitive and strips leading emoji/symbols.
 */
export function findMetricDefinition(name: string): MetricDefinition | undefined {
  // Direct match
  if (METRIC_DEFINITIONS[name]) return METRIC_DEFINITIONS[name];
  // Strip leading emoji/symbols and try again
  const cleaned = name.replace(/^[^\w]+/, "").trim();
  return METRIC_DEFINITIONS[cleaned] || Object.values(METRIC_DEFINITIONS).find(
    (d) => d.name.toLowerCase() === cleaned.toLowerCase()
  );
}
