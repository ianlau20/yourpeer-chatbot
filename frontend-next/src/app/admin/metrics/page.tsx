// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useState, useCallback } from "react";
import { useAdminStore } from "@/lib/admin/store";
import { MetricsSection } from "@/components/admin/metrics-section";
import { MetricRow, statusClass, fmtMetric } from "@/components/admin/metric-row";
import { MetricsSkeleton } from "@/components/admin/loading-skeleton";
import { MetricDetailDialog } from "@/components/admin/metric-detail-dialog";
import { findMetricDefinition } from "@/lib/admin/metric-definitions";
import type { MetricDefinition } from "@/lib/admin/metric-definitions";

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

  const [selectedMetric, setSelectedMetric] = useState<MetricDefinition | null>(null);

  const onMetricClick = useCallback((name: string) => {
    const def = findMetricDefinition(name);
    if (def) setSelectedMetric(def);
  }, []);

  const loading = (!statsSlice.data && statsSlice.loading)
    || (convosSlice.data.length === 0 && convosSlice.loading)
    || (queriesSlice.data.length === 0 && queriesSlice.loading);

  if (loading || !statsSlice.data) {
    return <MetricsSkeleton />;
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

  // Routing distribution
  const routing = stats.routing;
  const totalCategorized = routing?.total_categorized || 0;

  // Tone distribution
  const toneDist = stats.tone_distribution;
  const tones: Record<string, number> = toneDist?.tones || {};
  const toneEntries = Object.entries(tones).sort(([, a], [, b]) => b - a);
  const totalTurnsForToneRate =
    (toneDist?.total_with_tone || 0) + (toneDist?.turns_without_tone || 0);

  // Multi-intent
  const mi = stats.multi_intent;
  const queueOffers = mi?.queue_offers || 0;
  const queueDeclines = mi?.queue_declines || 0;
  const queueAcceptRate =
    queueOffers > 0 ? (queueOffers - queueDeclines) / queueOffers : null;

  return (
    <>
      <div className="bg-neutral-50 border border-neutral-200 rounded-lg px-3.5 py-2.5 text-sm text-neutral-500 mb-6">
        Metrics are computed from the audit log. When PILOT_DB_PATH is set, data
        persists across server restarts. <strong>n/a</strong> = not yet measurable.{" "}
        <strong>Click any metric name</strong> for a detailed explanation with
        formula and target rationale from{" "}
        <a
          href="https://github.com/ianlau20/yourpeer-chatbot/blob/llm-power/docs/METRICS.md"
          target="_blank"
          className="text-amber-600 hover:underline"
        >
          METRICS.md
        </a>
        .
      </div>

      {/* 1 · Intake Quality */}
      <MetricsSection
        title="1 · Intake Quality"
        description="How well the chatbot collects structured fields and guides users to a confirmed search. High task completion and low correction rates indicate the slot extractor and confirmation flow are working."
      >
        <MetricRow
          name="Task Completion Rate" onClick={onMetricClick}
          subtitle="% of service-intent sessions reaching a confirmed query"
          target="≥ 70% (pilot launch)"
          value={fmtMetric(taskCompletionRate, true)}
          status={statusClass(taskCompletionRate, 0.7, "gte", 0.55)}
        />
        <MetricRow
          name="Slot Confirmation Rate" onClick={onMetricClick}
          subtitle="% of queries that went through the explicit confirmation step"
          target="≥ 90%"
          value={fmtMetric(stats.slot_confirmation_rate, true)}
          status={statusClass(stats.slot_confirmation_rate, 0.9, "gte", 0.8)}
        />
        <MetricRow
          name="Slot Correction Rate" onClick={onMetricClick}
          subtitle="% of sessions where user corrects a slot after confirmation"
          target="≤ 15%"
          value={fmtMetric(stats.slot_correction_rate, true)}
          status={statusClass(stats.slot_correction_rate, 0.15, "lte", 0.25)}
        />
        <MetricRow
          name="Confirmation: Confirm Rate" onClick={onMetricClick}
          subtitle={`% of confirmation actions that are "Yes, search" (${cbTotal} actions)`}
          target="≥ 65% confirm"
          value={fmtMetric(cb?.confirm_rate ?? null, true)}
          status={statusClass(cb?.confirm_rate ?? null, 0.65, "gte", 0.5)}
        />
        <MetricRow
          name="Confirmation: Abandon Rate" onClick={onMetricClick}
          subtitle="% of sessions that reach confirmation but never confirm"
          target="≤ 10%"
          value={fmtMetric(cb?.abandon_rate ?? null, true)}
          status={statusClass(cb?.abandon_rate ?? null, 0.1, "lte", 0.2)}
        />
        <MetricRow
          name="Avg Turns to Query" onClick={onMetricClick}
          subtitle="Average turns from session start to first query (completed sessions)"
          target="≤ 5 turns (free-text)"
          value={fmtMetric(avgTurns, false, 1)}
          status={statusClass(avgTurns, 5, "lte", 7)}
        />
        <MetricRow
          name="Session Abandonment Rate" onClick={onMetricClick}
          subtitle="% of sessions with no query executed"
          target="≤ 30%"
          value={fmtMetric(abandonRate, true)}
          status={statusClass(abandonRate, 0.3, "lte", 0.45)}
        />
      </MetricsSection>

      {/* 2 · Answer Quality */}
      <MetricsSection
        title="2 · Answer Quality"
        description="Quality and usefulness of search results. Low no-result and relaxed rates indicate good query template coverage. Freshness measures how current the underlying service data is."
      >
        <MetricRow
          name="No-Result Rate" onClick={onMetricClick}
          subtitle="% of queries returning zero services after relaxed fallback"
          target="≤ 15% overall"
          value={fmtMetric(noResultRate, true)}
          status={statusClass(noResultRate, 0.15, "lte", 0.25)}
        />
        <MetricRow
          name="Relaxed Query Rate" onClick={onMetricClick}
          subtitle="% of queries that only returned results after relaxing strict filters"
          target="≤ 25%"
          value={fmtMetric(relaxedRateVal, true)}
          status={statusClass(relaxedRateVal, 0.25, "lte", 0.35)}
        />
        <MetricRow
          name="Data Freshness Rate" onClick={onMetricClick}
          subtitle={`% of returned service cards verified within last 90 days (${stats.data_freshness_detail?.cards_served || 0} cards served)`}
          target="≥ 80%"
          value={fmtMetric(stats.data_freshness_rate, true)}
          status={statusClass(stats.data_freshness_rate, 0.8, "gte", 0.6)}
        />
        <MetricRow name="Eligibility Fit Rate" onClick={onMetricClick} subtitle="% of results matching all stated user criteria" target="≥ 95%" value="By design (canary)" status="no-data" />
        <MetricRow
          name="User Feedback Score" onClick={onMetricClick}
          subtitle={`% of post-result feedback that is positive (${fbTotal} response${fbTotal !== 1 ? "s" : ""} so far)`}
          target="≥ 70% positive"
          value={fbDisplay}
          status={statusClass(stats.feedback_score, 0.7, "gte", 0.5)}
        />
      </MetricsSection>

      {/* 3 · Safety */}
      <MetricsSection
        title="3 · Safety"
        description="Crisis detection, escalation, and feedback metrics. Crisis detection must be 100% — any miss could leave a vulnerable person without resources. Escalation rate tracks peer navigator requests."
      >
        <MetricRow
          name="Crisis Detection Count" onClick={onMetricClick}
          subtitle="Total sessions where crisis language was detected and resources shown"
          target="Target: 100% of crisis messages"
          value={String(stats.total_crises)}
          status={stats.total_crises > 0 ? "on-target" : "no-data"}
        />
        <MetricRow name="Crisis False Positive Rate" onClick={onMetricClick} subtitle="% of crisis-flagged sessions that were not genuine crises" target="≤ 5%" value={null} status="no-data" />
        <MetricRow name="PII Leakage Rate" onClick={onMetricClick} subtitle="% of stored transcripts with detectable PII after redaction" target="0%" value={null} status="no-data" />
        <MetricRow name="Hallucination Rate" onClick={onMetricClick} subtitle="% of bot responses containing fabricated service data" target="< 1% (structural guarantee)" value="~0% by design" status="on-target" />
        <MetricRow
          name="Escalation Rate" onClick={onMetricClick}
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
      <MetricsSection
        title="4 · Conversation Quality"
        description="How well the chatbot handles emotional and conversational interactions beyond service search. Tracks emotional awareness, bot question handling, and whether users can find services through natural conversation."
      >
        <MetricRow
          name="Emotional Detection Rate" onClick={onMetricClick}
          subtitle={`% of sessions with an emotional turn (${stats.conversation_quality?.emotional_sessions || 0} sessions)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_rate ?? null, true)}
          status="tracking"
        />
        <MetricRow
          name="Emotional → Escalation Rate" onClick={onMetricClick}
          subtitle="% of emotional sessions where user subsequently asked for a peer navigator"
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_to_escalation ?? null, true)}
          status="tracking"
        />
        <MetricRow
          name="Emotional → Service Rate" onClick={onMetricClick}
          subtitle="% of emotional sessions where user eventually reached a service search"
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.emotional_to_service ?? null, true)}
          status="tracking"
        />
        <MetricRow
          name="Bot Question Rate" onClick={onMetricClick}
          subtitle={`% of turns asking about bot capabilities (${stats.conversation_quality?.bot_question_turns || 0} turns)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.bot_question_rate ?? null, true)}
          status="tracking"
        />
        <MetricRow
          name="Bot Question → Frustration Rate" onClick={onMetricClick}
          subtitle="% of bot-question sessions followed by frustration"
          target="≤ 10%"
          value={fmtMetric(stats.conversation_quality?.bot_question_to_frustration ?? null, true)}
          status={statusClass(stats.conversation_quality?.bot_question_to_frustration ?? null, 0.1, "lte", 0.2)}
        />
        <MetricRow
          name="Conversational Discovery Rate" onClick={onMetricClick}
          subtitle={`% of query sessions that included a conversational turn (${stats.conversation_quality?.conversational_discovery || 0} sessions)`}
          target="Baseline tracking"
          value={fmtMetric(stats.conversation_quality?.conversational_discovery_rate ?? null, true)}
          status="tracking"
        />
      </MetricsSection>

      {/* 4b · Routing Distribution */}
      <MetricsSection
        title="4b · Routing Distribution"
        description={`How user messages are routed across ${totalCategorized} categorized turns. "General (LLM)" is the highest-risk category — the LLM fully generates the response with no template grounding.`}
      >
        <MetricRow
          name="Service Flow"
          subtitle="Turns routed to service search, confirmation, or slot-filling"
          target="Largest bucket"
          value={`${routing?.buckets?.service_flow || 0} turns`}
          status={totalCategorized > 0 ? "tracking" : "no-data"}
          statusOverride={totalCategorized > 0 ? `${Math.round(((routing?.buckets?.service_flow || 0) / totalCategorized) * 100)}%` : undefined}
        />
        <MetricRow
          name="Conversational (Safe)"
          subtitle="Greetings, thanks, help, bot identity, reset — deterministic handlers"
          target="—"
          value={`${routing?.buckets?.conversational || 0} turns`}
          status={totalCategorized > 0 ? "tracking" : "no-data"}
          statusOverride={totalCategorized > 0 ? `${Math.round(((routing?.buckets?.conversational || 0) / totalCategorized) * 100)}%` : undefined}
        />
        <MetricRow
          name="Post-Results Questions"
          subtitle="Follow-up questions about displayed services — answered from card data, no LLM"
          target="Baseline tracking"
          value={`${routing?.category_distribution?.post_results || 0} turns`}
          status={totalCategorized > 0 ? "tracking" : "no-data"}
          statusOverride={totalCategorized > 0 ? `${Math.round(((routing?.category_distribution?.post_results || 0) / totalCategorized) * 100)}%` : undefined}
        />
        <MetricRow
          name="Emotional / Frustrated / Confused"
          subtitle="Tone-aware responses with empathetic framing"
          target="—"
          value={`${routing?.buckets?.emotional || 0} turns`}
          status={totalCategorized > 0 ? "tracking" : "no-data"}
          statusOverride={totalCategorized > 0 ? `${Math.round(((routing?.buckets?.emotional || 0) / totalCategorized) * 100)}%` : undefined}
        />
        <MetricRow
          name="Safety (Crisis + Escalation)"
          subtitle="Crisis resources shown or peer navigator offered"
          target="—"
          value={`${routing?.buckets?.safety || 0} turns`}
          status={totalCategorized > 0 ? "tracking" : "no-data"}
          statusOverride={totalCategorized > 0 ? `${Math.round(((routing?.buckets?.safety || 0) / totalCategorized) * 100)}%` : undefined}
        />
        <MetricRow
          name="⚠ General (LLM-Generated)" onClick={onMetricClick}
          subtitle="Turns where the LLM fully generates the response — no template grounding"
          target="≤ 15% of turns"
          value={fmtMetric(routing?.general_rate ?? null, true)}
          status={statusClass(routing?.general_rate ?? null, 0.15, "lte", 0.25)}
        />
        {routing?.category_distribution && Object.keys(routing.category_distribution).length > 0 && (
          <MetricRow
            name="Full Category Breakdown"
            subtitle={Object.entries(routing.category_distribution as Record<string, number>)
              .sort(([, a], [, b]) => (b as number) - (a as number))
              .map(([cat, count]) => `${cat}: ${count}`)
              .join(" · ")}
            target="—"
            value={`${Object.keys(routing.category_distribution).length} categories`}
            status="tracking"
          />
        )}
      </MetricsSection>

      {/* 4c · Tone Distribution */}
      <MetricsSection
        title="4c · Tone Distribution"
        description="Detected emotional tones across all turns. Tones are independent of routing — a turn can have both a service intent and an emotional tone."
      >
        {toneEntries.length > 0 ? (
          toneEntries.map(([tone, count]) => {
            const pct = totalTurnsForToneRate > 0 ? Math.round((count / totalTurnsForToneRate) * 100) : null;
            return (
              <MetricRow
                key={tone}
                name={tone.charAt(0).toUpperCase() + tone.slice(1)}
                subtitle={`${count} turn${count !== 1 ? "s" : ""} detected`}
                target="Baseline tracking"
                value={fmtMetric(
                  totalTurnsForToneRate > 0 ? count / totalTurnsForToneRate : null,
                  true,
                )}
                status={pct !== null ? "tracking" : "no-data"}
                statusOverride={pct !== null ? `${pct}%` : undefined}
              />
            );
          })
        ) : (
          <MetricRow
            name="No tones detected yet"
            subtitle="Tone data populates after the split classifier processes messages"
            target="—"
            value={null}
            status="no-data"
          />
        )}
        <MetricRow
          name="Turns Without Tone"
          subtitle="Neutral turns — no emotional tone detected"
          target="—"
          value={`${toneDist?.turns_without_tone || 0} turns`}
          status={totalTurnsForToneRate > 0 ? "tracking" : "no-data"}
          statusOverride={totalTurnsForToneRate > 0 ? `${Math.round(((toneDist?.turns_without_tone || 0) / totalTurnsForToneRate) * 100)}%` : undefined}
        />
      </MetricsSection>

      {/* 4d · Multi-Intent Queue */}
      <MetricsSection
        title="4d · Multi-Intent Queue"
        description="Tracks how often users request multiple services and whether they accept or decline the queued follow-up offers."
      >
        <MetricRow
          name="Queue Offers" onClick={onMetricClick}
          subtitle="Times the bot offered a second service after delivering results"
          target="Baseline tracking"
          value={String(queueOffers)}
          status={queueOffers > 0 ? "tracking" : "no-data"}
          statusOverride={totalSessions > 0 && queueOffers > 0 ? `${Math.round((queueOffers / totalSessions) * 100)}% of sessions` : undefined}
        />
        <MetricRow
          name="Queue Declines" onClick={onMetricClick}
          subtitle="Times the user declined a queued service offer"
          target="Baseline tracking"
          value={String(queueDeclines)}
          status={queueDeclines > 0 ? "tracking" : "no-data"}
          statusOverride={queueOffers > 0 && queueDeclines > 0 ? `${Math.round((queueDeclines / queueOffers) * 100)}% of offers` : undefined}
        />
        <MetricRow
          name="Queue Accept Rate" onClick={onMetricClick}
          subtitle="% of queue offers that were accepted (user searched the next service)"
          target="Baseline tracking"
          value={fmtMetric(queueAcceptRate, true)}
          status={queueAcceptRate !== null ? "tracking" : "no-data"}
          statusOverride={queueAcceptRate !== null ? `${Math.round(queueAcceptRate * 100)}% accepted` : undefined}
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
        <MetricRow name="Referral Success Rate" onClick={onMetricClick} subtitle="% of users who confirm visiting the referred service" target="≥ 75% of opt-in users" value={null} status="no-data" phase="Post-pilot" />
        <MetricRow name="Service Accuracy Rate" onClick={onMetricClick} subtitle="% of post-visit feedback where details matched reality" target="≥ 85%" value={null} status="no-data" phase="Post-pilot" />
        <MetricRow name="Outcome Linkage" onClick={onMetricClick} subtitle="Correlate success rates with user profile and location" target="Baseline established" value={null} status="no-data" phase="Post-pilot" />
      </MetricsSection>

      {/* Metric detail dialog */}
      {selectedMetric && (
        <MetricDetailDialog
          metric={selectedMetric}
          onClose={() => setSelectedMetric(null)}
        />
      )}
    </>
  );
}
