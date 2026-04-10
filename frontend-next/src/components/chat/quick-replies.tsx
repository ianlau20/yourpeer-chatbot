// Copyright (c) 2024 Streetlives, Inc.
// Use of this source code is governed by an MIT-style license.

"use client";

import type { QuickReply } from "@/lib/chat/types";

interface QuickRepliesProps {
  replies: QuickReply[];
  onSelect: (value: string) => void;
}

const btnClass =
  "px-4 py-2.5 rounded-full border-[1.5px] border-neutral-200 bg-white text-neutral-900 text-sm font-medium whitespace-nowrap transition-all hover:bg-amber-300 hover:border-amber-300 hover:shadow-md hover:-translate-y-px active:translate-y-0 active:scale-[0.97]";

export function QuickReplies({ replies, onSelect }: QuickRepliesProps) {
  return (
    <div
      role="group"
      aria-label="Quick reply options"
      className="flex flex-wrap gap-2 self-start max-w-[92%] animate-in fade-in slide-in-from-bottom-1"
    >
      {replies.map((qr) =>
        qr.href ? (
          // External action (e.g. tel: link) — renders as <a> to trigger
          // the native handler (phone dialer on mobile, calling app on desktop).
          <a
            key={qr.value}
            href={qr.href}
            aria-label={qr.label}
            className={btnClass + " inline-block text-center no-underline"}
          >
            {qr.label}
          </a>
        ) : (
          <button
            key={qr.value}
            type="button"
            onClick={() => onSelect(qr.value)}
            aria-label={qr.value}
            className={btnClass}
          >
            {qr.label}
          </button>
        ),
      )}
    </div>
  );
}
