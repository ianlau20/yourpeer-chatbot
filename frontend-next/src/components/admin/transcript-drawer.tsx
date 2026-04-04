// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { AuditEvent } from "@/lib/chat/types";

interface TranscriptDrawerProps {
  sessionId: string;
  events: AuditEvent[] | null;
  loading: boolean;
  onClose: () => void;
}

export function TranscriptDrawer({
  sessionId,
  events,
  loading,
  onClose,
}: TranscriptDrawerProps) {
  const turns = events?.filter((e) => e.type === "conversation_turn") ?? [];
  const crises = events?.filter((e) => e.type === "crisis_detected") ?? [];

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 z-50 animate-in fade-in" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white border border-neutral-200 rounded-2xl max-w-[700px] w-[90%] max-h-[80vh] overflow-y-auto p-7 z-50 animate-in fade-in slide-in-from-bottom-2">
          <div className="flex justify-between items-center mb-5">
            <Dialog.Title className="text-base font-semibold">
              Session {sessionId.slice(0, 12)}…
            </Dialog.Title>
            <Dialog.Close asChild>
              <button aria-label="Close transcript" className="w-8 h-8 rounded-lg border border-neutral-200 bg-neutral-50 text-neutral-400 flex items-center justify-center transition hover:border-red-300 hover:text-red-500">
                <X size={16} />
              </button>
            </Dialog.Close>
          </div>

          {loading && (
            <p className="text-neutral-400 text-sm">Loading…</p>
          )}

          {!loading && turns.length === 0 && crises.length === 0 && (
            <p className="text-neutral-400 text-sm">
              No conversation turns found.
            </p>
          )}

          {turns.map((e, i) => {
            const slotStr = Object.entries(e.slots || {})
              .filter(([, v]) => v != null)
              .map(([k, v]) => `${k}=${v}`)
              .join(", ");
            const meta: string[] = [];
            if (slotStr) meta.push(`slots: {${slotStr}}`);
            if (e.services_count) meta.push(`${e.services_count} service(s) delivered`);
            if (e.quick_replies?.length)
              meta.push(`buttons: ${e.quick_replies.join(", ")}`);

            return (
              <div key={i} className="mb-4 animate-in fade-in slide-in-from-bottom-1">
                {/* User turn */}
                <div className="bg-amber-50/60 border-l-[3px] border-amber-400 px-3.5 py-2.5 rounded-r-lg mb-2">
                  <div className="text-[0.7rem] font-semibold uppercase tracking-wider text-amber-600 mb-1">
                    User
                  </div>
                  <div className="text-sm whitespace-pre-wrap leading-relaxed">
                    {e.user_message}
                  </div>
                </div>
                {/* Bot turn */}
                <div className="bg-neutral-50 border-l-[3px] border-neutral-300 px-3.5 py-2.5 rounded-r-lg">
                  <div className="text-[0.7rem] font-semibold uppercase tracking-wider text-neutral-400 mb-1">
                    Bot
                  </div>
                  <div className="text-sm whitespace-pre-wrap leading-relaxed">
                    {e.bot_response}
                  </div>
                  {meta.length > 0 && (
                    <div className="text-xs text-neutral-400 mt-1.5 font-mono">
                      {meta.join(" · ")}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {crises.map((e, i) => (
            <div
              key={`crisis-${i}`}
              className="bg-red-50 border-l-[3px] border-red-500 px-3.5 py-2.5 rounded-r-lg mb-2"
            >
              <div className="text-[0.7rem] font-semibold uppercase tracking-wider text-red-600 mb-1">
                ⚠ Crisis Detected
              </div>
              <div className="text-sm">
                {e.crisis_category}: {e.user_message}
              </div>
            </div>
          ))}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
