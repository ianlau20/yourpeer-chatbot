// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import type {
  ChatResponse,
  FeedbackRating,
  AdminStats,
  ConversationSummary,
  AuditEvent,
  QueryLogEntry,
  EvalReport,
  EvalRunStatus,
} from "./types";

// ---------------------------------------------------------------------------
// Chat API
// ---------------------------------------------------------------------------

export async function sendChatMessage(
  message: string,
  sessionId: string | null,
): Promise<ChatResponse> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    if (res.status === 429 && data?.detail) {
      const msg = data.crisis_resources
        ? `${data.detail}\n\n${data.crisis_resources}`
        : data.detail;
      throw new Error(msg);
    }
    throw new Error(`Request failed with status ${res.status}`);
  }
  return res.json();
}

export async function sendFeedback(
  sessionId: string,
  rating: FeedbackRating,
): Promise<void> {
  // Fire and forget — feedback loss is acceptable
  await fetch("/api/chat/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, rating }),
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Admin API
// ---------------------------------------------------------------------------

const ADMIN_API = "/api/admin";

export async function fetchAdminStats(): Promise<AdminStats> {
  const res = await fetch(`${ADMIN_API}/stats`);
  if (!res.ok) throw new Error("Failed to load stats");
  return res.json();
}

export async function fetchConversations(
  limit = 100,
): Promise<ConversationSummary[]> {
  const res = await fetch(`${ADMIN_API}/conversations?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load conversations");
  return res.json();
}

export async function fetchConversationDetail(
  sessionId: string,
): Promise<AuditEvent[]> {
  const res = await fetch(`${ADMIN_API}/conversations/${sessionId}`);
  if (!res.ok) throw new Error("Failed to load conversation");
  return res.json();
}

export async function fetchEvents(
  limit = 100,
): Promise<AuditEvent[]> {
  const res = await fetch(`${ADMIN_API}/events?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load events");
  return res.json();
}

export async function fetchQueries(limit = 200): Promise<QueryLogEntry[]> {
  const res = await fetch(`${ADMIN_API}/queries?limit=${limit}`);
  if (!res.ok) throw new Error("Failed to load queries");
  return res.json();
}

export async function fetchEvalResults(): Promise<EvalReport | null> {
  const res = await fetch(`${ADMIN_API}/eval`);
  if (!res.ok) throw new Error("Failed to load eval results");
  const data = await res.json();
  return data.results === null ? null : data;
}

export async function triggerEvalRun(
  scenarios?: number,
  category?: string,
): Promise<{ detail: string }> {
  const params = new URLSearchParams();
  if (scenarios) params.set("scenarios", String(scenarios));
  if (category) params.set("category", category);
  const res = await fetch(`${ADMIN_API}/eval/run?${params}`, { method: "POST" });
  if (!res.ok) {
    const data = await res.json();
    throw new Error(data.detail || "Failed to start eval");
  }
  return res.json();
}

export async function fetchEvalStatus(): Promise<EvalRunStatus> {
  const res = await fetch(`${ADMIN_API}/eval/status`);
  if (!res.ok) throw new Error("Failed to check eval status");
  return res.json();
}
