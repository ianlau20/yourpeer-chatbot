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
