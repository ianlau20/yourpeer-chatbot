// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useState } from "react";
import { fetchAdminStats, fetchEvents } from "@/lib/chat/api";
import type { AdminStats, AuditEvent } from "@/lib/chat/types";
import { StatCard } from "@/components/admin/stat-card";
import { EventFeed } from "@/components/admin/event-feed";

export default function OverviewPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    Promise.all([fetchAdminStats(), fetchEvents(20)])
      .then(([s, e]) => {
        setStats(s);
        setEvents(e);
      })
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="text-3xl mb-3">📊</div>
        <p>No data yet. Start chatting to generate activity.</p>
      </div>
    );
  }

  if (!stats) {
    return <p className="text-neutral-400 text-sm">Loading…</p>;
  }

  const relaxedRate = stats.relaxed_query_rate || 0;
  const relaxedCls =
    relaxedRate > 0.35 ? "text-red-600" : relaxedRate > 0.25 ? "text-amber-500" : "text-green-600";

  const totalFeedback = (stats.feedback_up || 0) + (stats.feedback_down || 0);
  const feedbackDisplay =
    totalFeedback > 0 ? `${Math.round((stats.feedback_score ?? 0) * 100)}% 👍` : "—";
  const feedbackCls =
    stats.feedback_score === null
      ? ""
      : stats.feedback_score >= 0.7
        ? "text-green-600"
        : stats.feedback_score >= 0.5
          ? "text-amber-500"
          : "text-red-600";

  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3 mb-6">
        <StatCard label="Sessions" value={stats.unique_sessions} colorClass="text-amber-500" />
        <StatCard label="Turns" value={stats.total_turns} />
        <StatCard label="Queries Executed" value={stats.total_queries} />
        <StatCard
          label="Crises Detected"
          value={stats.total_crises}
          colorClass={stats.total_crises > 0 ? "text-red-600" : "text-green-600"}
        />
        <StatCard
          label="User Feedback"
          value={feedbackDisplay}
          colorClass={feedbackCls}
          note={totalFeedback > 0 ? `${totalFeedback} responses · target ≥ 70%` : "target ≥ 70%"}
        />
        <StatCard
          label="Relaxed Query Rate"
          value={`${(relaxedRate * 100).toFixed(0)}%`}
          colorClass={relaxedCls}
          note="target ≤ 25%"
        />
      </div>

      <div className="mb-7">
        <h2 className="text-base font-semibold mb-4">Recent Activity</h2>
        <EventFeed events={events} />
      </div>
    </>
  );
}
