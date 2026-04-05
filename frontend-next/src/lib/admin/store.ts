// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import { create } from "zustand";
import {
  fetchAdminStats,
  fetchConversations as apiConversations,
  fetchQueries as apiQueries,
  fetchEvents as apiEvents,
  fetchEvalResults as apiEvalResults,
} from "@/lib/chat/api";
import type {
  AdminStats,
  ConversationSummary,
  QueryLogEntry,
  AuditEvent,
  EvalReport,
} from "@/lib/chat/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DataSlice<T> {
  data: T;
  loading: boolean;
  error: boolean;
  lastFetchedAt: number;
}

function emptySlice<T>(initial: T): DataSlice<T> {
  return { data: initial, loading: false, error: false, lastFetchedAt: 0 };
}

interface AdminStore {
  stats: DataSlice<AdminStats | null>;
  conversations: DataSlice<ConversationSummary[]>;
  queries: DataSlice<QueryLogEntry[]>;
  events: DataSlice<AuditEvent[]>;
  evalResults: DataSlice<EvalReport | null | undefined>;

  fetchStats: () => Promise<void>;
  fetchConversations: () => Promise<void>;
  fetchQueries: () => Promise<void>;
  fetchEvents: () => Promise<void>;
  fetchEvalResults: () => Promise<void>;
  /** Force all slices to re-fetch on next access. */
  invalidateAll: () => void;
  /** Force a single slice to re-fetch on next access. */
  invalidate: (key: "stats" | "conversations" | "queries" | "events" | "evalResults") => void;
}

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Data older than this is considered stale and will be re-fetched. */
const STALE_AFTER_MS = 30_000; // 30 seconds

/** Fixed limits — use the largest value any consumer needs. */
const CONVERSATIONS_LIMIT = 200;
const QUERIES_LIMIT = 500;
const EVENTS_LIMIT = 50;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isStale(slice: DataSlice<unknown>): boolean {
  return Date.now() - slice.lastFetchedAt > STALE_AFTER_MS;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useAdminStore = create<AdminStore>((set, get) => ({
  stats: emptySlice(null),
  conversations: emptySlice([]),
  queries: emptySlice([]),
  events: emptySlice([]),
  evalResults: emptySlice(undefined),

  fetchStats: async () => {
    const { stats } = get();
    if (stats.loading || !isStale(stats)) return;

    set({ stats: { ...stats, loading: true, error: false } });
    try {
      const data = await fetchAdminStats();
      set({ stats: { data, loading: false, error: false, lastFetchedAt: Date.now() } });
    } catch {
      set({ stats: { ...get().stats, loading: false, error: true } });
    }
  },

  fetchConversations: async () => {
    const { conversations } = get();
    if (conversations.loading || !isStale(conversations)) return;

    set({ conversations: { ...conversations, loading: true, error: false } });
    try {
      const data = await apiConversations(CONVERSATIONS_LIMIT);
      set({ conversations: { data, loading: false, error: false, lastFetchedAt: Date.now() } });
    } catch {
      set({ conversations: { ...get().conversations, loading: false, error: true } });
    }
  },

  fetchQueries: async () => {
    const { queries } = get();
    if (queries.loading || !isStale(queries)) return;

    set({ queries: { ...queries, loading: true, error: false } });
    try {
      const data = await apiQueries(QUERIES_LIMIT);
      set({ queries: { data, loading: false, error: false, lastFetchedAt: Date.now() } });
    } catch {
      set({ queries: { ...get().queries, loading: false, error: true } });
    }
  },

  fetchEvents: async () => {
    const { events } = get();
    if (events.loading || !isStale(events)) return;

    set({ events: { ...events, loading: true, error: false } });
    try {
      const data = await apiEvents(EVENTS_LIMIT);
      set({ events: { data, loading: false, error: false, lastFetchedAt: Date.now() } });
    } catch {
      set({ events: { ...get().events, loading: false, error: true } });
    }
  },

  fetchEvalResults: async () => {
    const { evalResults } = get();
    if (evalResults.loading || !isStale(evalResults)) return;

    set({ evalResults: { ...evalResults, loading: true, error: false } });
    try {
      const data = await apiEvalResults();
      set({ evalResults: { data, loading: false, error: false, lastFetchedAt: Date.now() } });
    } catch {
      set({ evalResults: { ...get().evalResults, loading: false, error: true } });
    }
  },

  invalidateAll: () => {
    const reset = { lastFetchedAt: 0 };
    set((s) => ({
      stats: { ...s.stats, ...reset },
      conversations: { ...s.conversations, ...reset },
      queries: { ...s.queries, ...reset },
      events: { ...s.events, ...reset },
      evalResults: { ...s.evalResults, ...reset },
    }));
  },

  invalidate: (key) => {
    set((s) => ({
      [key]: { ...s[key], lastFetchedAt: 0 },
    }));
  },
}));
