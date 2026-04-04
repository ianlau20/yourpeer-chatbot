// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import type { QueryLogEntry } from "@/lib/chat/types";

interface QueryLogTableProps {
  queries: QueryLogEntry[];
}

export function QueryLogTable({ queries }: QueryLogTableProps) {
  if (queries.length === 0) {
    return (
      <div className="text-center py-16 text-neutral-400">
        <div className="text-3xl mb-3">🔍</div>
        <p>No database queries executed yet. Complete a search to see query logs.</p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-neutral-200 rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            {["Time", "Template", "Params", "Results", "Latency", "Session"].map(
              (h) => (
                <th
                  key={h}
                  className="text-left px-4 py-3 text-xs uppercase tracking-wider text-neutral-400 font-semibold border-b border-neutral-200 whitespace-nowrap"
                >
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {[...queries].reverse().map((q, i) => {
            const params = Object.entries(q.params || {})
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ");
            return (
              <tr key={i} className="hover:bg-neutral-50/50">
                <td className="px-4 py-2.5 font-mono text-xs border-b border-neutral-100">
                  {new Date(q.timestamp).toLocaleTimeString()}
                </td>
                <td className="px-4 py-2.5 border-b border-neutral-100">
                  <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-600">
                    {q.template_name}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-xs border-b border-neutral-100 max-w-[350px] truncate">
                  {params}
                </td>
                <td className="px-4 py-2.5 border-b border-neutral-100">
                  {q.result_count}
                  {q.relaxed && (
                    <span className="ml-1 inline-block px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-600">
                      relaxed
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs border-b border-neutral-100">
                  {q.execution_ms}ms
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-neutral-400 border-b border-neutral-100">
                  {q.session_id ? `${q.session_id.slice(0, 8)}…` : ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
