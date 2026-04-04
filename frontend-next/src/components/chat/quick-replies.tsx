// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import type { QuickReply } from "@/lib/chat/types";

interface QuickRepliesProps {
  replies: QuickReply[];
  onSelect: (value: string) => void;
}

export function QuickReplies({ replies, onSelect }: QuickRepliesProps) {
  return (
    <div className="flex flex-wrap gap-2 self-start max-w-[92%] animate-in fade-in slide-in-from-bottom-1">
      {replies.map((qr) => (
        <button
          key={qr.value}
          type="button"
          onClick={() => onSelect(qr.value)}
          className="px-4 py-2.5 rounded-full border-[1.5px] border-neutral-200 bg-white text-neutral-900 text-sm font-medium whitespace-nowrap transition-all hover:bg-amber-300 hover:border-amber-300 hover:shadow-md hover:-translate-y-px active:translate-y-0 active:scale-[0.97]"
        >
          {qr.label}
        </button>
      ))}
    </div>
  );
}
