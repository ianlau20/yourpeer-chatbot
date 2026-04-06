// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect } from "react";
import { useAdminStore } from "@/lib/admin/store";
import { MetricsSection } from "@/components/admin/metrics-section";
import { MetricRow, statusClass, fmtMetric } from "@/components/admin/metric-row";

export default function MetricsPage() {
  const {
    stats: statsSlice,
    conversations: convosSlice,
    queries: queriesSlice,
    fetchStats,
    fetchConversations,
    fetchQueries,
  } = useAdminStore();

  useEffect(() => {
    fetchStats();
    fetchConversations();
    fetchQueries();
  }, [fetchStats, fetchConversations, fetchQueries]);

  const loading = (!statsSlice.data && statsSlice.loading)
    || (convosSlice.data.length === 0 && convosSlice.loading)
    || (queriesSlice.data.length === 0 && queriesSlice.loading);

  if (loading || !statsSlice.data) {
    return <p className="text-neutral-400 text-sm">Loading metrics…</p>;
  }

  const stats = statsSlice.data;
  const convos = convosSlice.data;
  const queries = queriesSlice.data;

  // Derived metrics
  const totalSessions = stats.unique_sessions || 0;
  const totalQueries = stats.total_queries || 0;
  const serviceIntentSessions = stats.service_intent_sessions || 0;

  // Fix: denominator is sessions with service intent, not ALL sessions
  const taskCompletionRate =
    serviceIntentSessions > 0 && totalQueries > 0
      ? Math.min(totalQueries / serviceIntentSessions, 1)
      : null;

  const zeroResultQueries = queries.filter((q) => q.result_count === 0).length;
  const noResultRate = queries.length > 0 ? zeroResultQueries / queries.length : null;

  const relaxedRateVal = totalQueries > 0 ? stats.relaxed_query_rate : null;

  const abandonedSessions = convos.filter(
    (c) => c.services_delivered === 0 && c.turn_count > 0,
  ).length;
  const abandonRate = totalSessions > 0 ? abandonedSessions / totalSessions : null;

  const completedConvos = convos.filter((c) => c.services_delivered > 0);
  const avgTurns =
    completedConvos.length > 0
      ? completedConvos.reduce((s, c) => s + c.turn_count, 0) / completedConvos.length
      : null;

  const fbTotal = (stats.feedback_up || 0) + (stats.feedback_down || 0);
  const fbDisplay = fbTotal > 0 ? fmtMetric(stats.feedback_score, true) : null;

  // Confirmation breakdown from the backend
  const cb = stats.confirmation_breakdown;
  const cbTotal = cb?.total_actions || 0;

  return (
    <>
      <div className="bg-neutral-50 border border-neutral-200 rounded-lg px-3.5 py-2.5 text-sm text-neutral-500 mb-6">
        Metrics are computed from the in-memory audit log. Data resets on server
        restart. <strong>n/a</strong> = not yet measurable from audit log alone.
        See{" "}
        <a
          href="https://github.com/ianlau20/yourpeer-chatbot/blob/llm-power/docs/METRICS.md"
          target="_blank"
          className="text-amber-600 hover:underline"
        >
          METRICS.md
        </a>{" "}
        for full definitions.
      </div>

      {/* 1 · Intake Quality */}
      <MetricsSection title="1 · Intake Quality">
        <MetricRow
          name="Task Completion Rate"
          subtitle="% of service-intent sessions reaching a confirmed query"
          target="≥ 70% (pilot launch)"
          value={fmtMetric(taskCompletionRate, true)}
          status={statusClass(taskCompletionRate, 0.7, "gte", 0.55)}
        />
        <MetricRow
          name="Slot Confirmation Rate"
          subtitle="% of queries that went through the explicit confirmation step"
          target="≥ 90%"
          value={fmtMetric(stats.slot_confirmation_rate, true)}
          status={statusClass(stats.slot_confirmation_rate, 0.9, "gte", 0.8)}
        />
        <MetricRow
          name="Slot Correction Rate"
          subtitle="% of sessions where user corrects a slot after confirmation"
          target="≤ 15%"
          value={fmtMetric(stats.slot_correction_rate, true)}
          status={statusClass(stats.slot_correction_rate, 0.15, "lte", 0.25)}
        />
        <MetricRow
          name="Confirmation: Confirm Rate"
          subtitle={`% of confirmation actions that are "Yes, search" (${cbTotal} actions)`}
          target="≥ 65% confirm"
          value={fmtMetric(cb?.confirm_rate ?? null, true)}
          status={statusClass(cb?.confirm_rate ?? null, 0.65, "gte", 0.5)}
        />
        <MetricRow
          name="Confirmation: Abandon Rate"
          subtitle="% of sessions that reach confirmation but never confirm"
          target="≤ 10%"
          value={fmtMetric(cb?.abandon_rate ?? null, true)}
          status={statusClass(cb?.abandon_rate ?? null, 0.1, "lte", 0.2)}
        />
        <MetricRow
          name="Avg Turns to Query"
          subtitle="Average turns from session start to first query (completed sessions)"
          target="≤ 5 turns (free-text)"
          value={fmtMetric(avgTurns, false, 1)}
          status={statusClass(avgTurns, 5, "lte", 7)}
        />
        <MetricRow
          name="Session Abandonment Rate"
          subtitle="% of sessions with no query executed"
          target="≤ 30%"
          value={fmtMetric(abandonRate, true)}
          status={statusClass(abandonRate, 0.3, "lte", 0.45)}
        />
      </MetricsSection>

      {/* 2 · Answer Quality */}
      <MetricsSection title="2 · Answer Quality">
        <MetricRow
          name="No-Result Rate"
          subtitle="% of queries returning zero services after relaxed fallback"
          target="≤ 15% overall"
          value={fmtMetric(noResultRate, true)}
          status={statusClass(noResultRate, 0.15, "lte", 0.25)}
        />
        <MetricRow
          name="Relaxed Query Rate"
          subtitle="% of queries that only returned results after relaxing strict filters"
          target="≤ 25%"
          value={fmtMetric(relaxedRateVal, true)}
          status={statusClass(relaxedRateVal, 0.25, "lte", 0.35)}
        />
        <MetricRow
          name="Data Freshness Rate"
          subtitle={`% of returned service cards verified within last 90 days (${stats.data_freshness_detail?.cards_served || 0} cards served)`}
          target="≥ 80%"
          value={fmtMetric(stats.data_freshness_rate, true)}
          status={statusClass(stats.data_freshness_rate, 0.8, "gte", 0.6)}
        />
        <MetricRow name="Eligibility Fit Rate" subtitle="% of results matching all stated user criteria" target="≥ 95%" value="By design (canary)" status="no-data" />
        <MetricRow
          name="User Feedback Score"
          subtitle={`% of post-result feedback that is positive (${fbTotal} response${fbTotal !== 1 ? "s" : ""} so far)`}
          target="≥ 70% positive"
          value={fbDisplay}
          status={statusClass(stats.feedback_score, 0.7, "gte", 0.5)}
        />
      </MetricsSection>

      {/* 3 · Safety */}
      <MetricsSection title="3 · Safety">
        <MetricRow
          name="Crisis Detection Count"
          subtitle="Total sessions where crisis language was detected and resources shown"
          target="Target: 100% of crisis messages"
          value={String(stats.total_crises)}
          status={stats.total_crises > 0 ? "on-target" : "no-data"}
        />
        <MetricRow name="Crisis False Positive Rate" subtitle="% of crisis-flagged sessions that were not genuine crises" target="≤ 5%" value={null} status="no-data" />
        <MetricRow name="PII Leakage Rate" subtitle="% of stored transcripts with detectable PII after redaction" target="0%" value={null} status="no-data" />
        <MetricRow name="Hallucination Rate" subtitle="% of bot responses containing fabricated service data" target="< 1% (structural guarantee)" value="~0% by design" status="on-target" />
        <MetricRow
          name="Escalation Rate"
          subtitle="% of sessions where user requests a human peer navigator"
          target="Baseline tracking only"
          value={fmtMetric(
            totalSessions > 0 ? (stats.total_escalations || 0) / totalSessions : null,
            true,
          )}
          status="no-data"
        />
      </MetricsSection>

      {/* 4 · Conversation Quality */}
      <MetricsSection title="4 · Conversation Quality">
        <MetricRow
          name="Emotional Detection Rate"
          subtitle={`% of sessions with an emotional turn (${stats.conversation_quality?.emotional_sessions || 0} sessions)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_rate ?? null, true)}
          status="no-data"
        />
        <MetricRow
          name="Emotional → Escalation Rate"
          subtitle="% of emotional sessions where user subsequently asked for a peer navigator"
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_to_escalation ?? null, true)}
          status="no-data"
        />
        <MetricRow
          name="Emotional → Service Rate"
          subtitle="% of emotional sessions where user eventually reached a service search"
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_to_service ?? null, true)}
          status="no-data"
        />
        <MetricRow
          name="Bot Question Rate"
          subtitle={`% of turns asking about bot capabilities (${stats.conversation_quality?.bot_question_turns || 0} turns)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.bot_question_rate ?? null, true)}
          status="no-data"
        />
        <MetricRow
          name="Bot Question → Frustration Rate"
          subtitle="% of bot-question sessions followed by frustration"
          target="≤ 10%"
          value={fmtMetric(stats.conversation_quality?.bot_question_to_frustration ?? null, true)}
          status={statusClass(stats.conversation_quality?.bot_question_to_frustration ?? null, 0.1, "lte", 0.2)}
        />
        <MetricRow
          name="Conversational Discovery Rate"
          subtitle={`% of query sessions that included a conversational turn (${stats.conversation_quality?.conversational_discovery || 0} sessions)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.conversational_discovery_rate ?? null, true)}
          status="no-data"
        />
      </MetricsSection>

      {/* 5 · System Quality */}
      <MetricsSection
        title="5 · System Quality — LLM-as-Judge Eval Targets"
        description="Run the eval suite from the Eval Results tab to populate scores. Critical failures on Safety or Hallucination Resistance are deploy blockers."
      >
        {[
          { key: "slot_extraction", label: "Slot Extraction Accuracy", target: "≥ 4.0 / 5.0" },
          { key: "dialog_efficiency", label: "Dialog Efficiency", target: "≥ 3.5 / 5.0" },
          { key: "response_tone", label: "Response Tone", target: "≥ 4.0 / 5.0" },
          { key: "safety_crisis", label: "Safety & Crisis Handling", target: "≥ 4.5 / 5.0 ⚠ blocker" },
          { key: "confirmation_ux", label: "Confirmation UX", target: "≥ 3.5 / 5.0" },
          { key: "privacy", label: "Privacy", target: "≥ 4.5 / 5.0" },
          { key: "hallucination_resistance", label: "Hallucination Resistance", target: "≥ 4.5 / 5.0 ⚠ blocker" },
          { key: "error_recovery", label: "Error Recovery", target: "≥ 3.5 / 5.0" },
        ].map((d) => (
          <MetricRow key={d.key} name={d.label} subtitle="LLM-as-judge score (1–5)" target={d.target} value={null} status="no-data" />
        ))}
      </MetricsSection>

      {/* 6 · Closed-Loop */}
      <MetricsSection
        title="6 · Closed-Loop Outcomes — Post-Pilot"
        description="These metrics require SMS follow-up infrastructure and privacy review. Not implemented in the pilot."
      >
        <MetricRow name="Referral Success Rate" subtitle="% of users who confirm visiting the referred service" target="≥ 75% of opt-in users" value={null} status="no-data" phase="Post-pilot" />
        <MetricRow name="Service Accuracy Rate" subtitle="% of post-visit feedback where details matched reality" target="≥ 85%" value={null} status="no-data" phase="Post-pilot" />
        <MetricRow name="Outcome Linkage" subtitle="Correlate success rates with user profile and location" target="Baseline established" value={null} status="no-data" phase="Post-pilot" />
      </MetricsSection>
    </>
  );
}
