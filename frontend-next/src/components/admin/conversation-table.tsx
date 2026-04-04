// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useState } from "react";
import type { ConversationSummary, AuditEvent } from "@/lib/chat/types";
import { fetchConversationDetail } from "@/lib/chat/api";
import { TranscriptDrawer } from "./transcript-drawer";

interface ConversationTableProps {
  conversations: ConversationSummary[];
}

export function ConversationTable({ conversations }: ConversationTableProps) {
  const [transcript, setTranscript] = useState<AuditEvent[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function openTranscript(sessionId: string) {
    setSelectedId(sessionId);
    setLoading(true);
    try {
      const events = await fetchConversationDetail(sessionId);
      setTranscript(events);
    } catch {
      setTranscript([]);
    } finally {
      setLoading(false);
    }
  }

  function closeTranscript() {
    setSelectedId(null);
    setTranscript(null);
  }

  if (conversations.length === 0) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="text-3xl mb-3">💬</div>
        <p>No conversations yet. Start chatting to see them here.</p>
      </div>
    );
  }

  return (
    <>
      <div className="bg-white border border-neutral-200 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
                Session
              </th>
              <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
                Turns
              </th>
              <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
                Outcome
              </th>
              <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
                Slots
              </th>
              <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
                Last Active
              </th>
            </tr>
          </thead>
          <tbody>
            {conversations.map((c) => {
              const slots =
                Object.entries(c.final_slots || {})
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ") || "—";
              return (
                <tr
                  key={c.session_id}
                  onClick={() => openTranscript(c.session_id)}
                  className="cursor-pointer hover:bg-amber-50/50 transition-colors"
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-neutral-500 border-b border-neutral-100">
                    {c.session_id.slice(0, 12)}…
                  </td>
                  <td className="px-4 py-2.5 border-b border-neutral-100">
                    {c.turn_count}
                  </td>
                  <td className="px-4 py-2.5 border-b border-neutral-100 space-x-1">
                    {c.services_delivered > 0 ? (
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-green-50 text-green-600">
                        {c.services_delivered} results
                      </span>
                    ) : (
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-neutral-100 text-neutral-400">
                        no results
                      </span>
                    )}
                    {c.crisis_detected && (
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-red-50 text-red-600">
                        crisis
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-sm border-b border-neutral-100 max-w-[300px] truncate">
                    {slots}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-neutral-400 border-b border-neutral-100">
                    {new Date(c.last_seen).toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selectedId && (
        <TranscriptDrawer
          sessionId={selectedId}
          events={transcript}
          loading={loading}
          onClose={closeTranscript}
        />
      )}
    </>
  );
}
