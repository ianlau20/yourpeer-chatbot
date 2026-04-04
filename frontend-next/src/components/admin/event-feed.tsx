// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import type { AuditEvent } from "@/lib/chat/types";

function typeBadge(type: string) {
  const label = type.replace("_", " ");
  const cls =
    type === "crisis_detected"
      ? "bg-red-50 text-red-600"
      : type === "query_execution"
        ? "bg-blue-50 text-blue-600"
        : type === "session_reset"
          ? "bg-amber-50 text-amber-600"
          : "bg-neutral-100 text-neutral-400";
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {label}
    </span>
  );
}

interface EventFeedProps {
  events: AuditEvent[];
}

export function EventFeed({ events }: EventFeedProps) {
  if (events.length === 0) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="text-3xl mb-3">💬</div>
        <p>No events yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-neutral-200 rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
              Time
            </th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
              Type
            </th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
              Detail
            </th>
            <th className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200">
              Session
            </th>
          </tr>
        </thead>
        <tbody>
          {[...events].reverse().map((e, i) => {
            const time = new Date(e.timestamp).toLocaleTimeString();
            let detail: React.ReactNode = "";

            if (e.type === "conversation_turn") {
              detail = (
                <span className="max-w-[300px] truncate block">
                  {e.user_message}
                </span>
              );
            } else if (e.type === "query_execution") {
              detail = (
                <>
                  {e.template_name} → {e.result_count} results ({e.execution_ms}ms)
                  {e.relaxed && (
                    <span className="ml-1 inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-600">
                      relaxed
                    </span>
                  )}
                </>
              );
            } else if (e.type === "crisis_detected") {
              detail = (
                <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-red-50 text-red-600">
                  {e.crisis_category}
                </span>
              );
            } else if (e.type === "session_reset") {
              detail = "Session cleared";
            }

            return (
              <tr key={i} className="hover:bg-neutral-50/50">
                <td className="px-4 py-2.5 font-mono text-xs border-b border-neutral-100">
                  {time}
                </td>
                <td className="px-4 py-2.5 border-b border-neutral-100">
                  {typeBadge(e.type)}
                </td>
                <td className="px-4 py-2.5 border-b border-neutral-100">
                  {detail}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-neutral-400 border-b border-neutral-100">
                  {e.session_id ? `${e.session_id.slice(0, 8)}…` : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
