// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useState } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import type { FeedbackRating } from "@/lib/chat/types";

interface FeedbackRowProps {
  onFeedback: (rating: FeedbackRating) => void;
}

export function FeedbackRow({ onFeedback }: FeedbackRowProps) {
  const [submitted, setSubmitted] = useState<FeedbackRating | null>(null);

  function submit(rating: FeedbackRating) {
    if (submitted) return;
    setSubmitted(rating);
    onFeedback(rating);
  }

  const label =
    submitted === "up"
      ? "Thanks for the feedback! 👍"
      : submitted === "down"
        ? "Thanks — we'll work to improve. 👎"
        : "Were these results helpful?";

  return (
    <div className="flex items-center gap-2.5 self-start px-0.5 py-1.5 animate-in fade-in slide-in-from-bottom-1">
      <span className="text-xs text-neutral-400">{label}</span>
      <button
        type="button"
        disabled={!!submitted}
        onClick={() => submit("up")}
        aria-label="Thumbs up"
        className={`w-8 h-8 rounded-lg border flex items-center justify-center transition-all disabled:cursor-default ${
          submitted === "up"
            ? "bg-green-100 border-green-300 text-green-700"
            : "border-neutral-200 bg-white text-neutral-500 hover:bg-neutral-50 hover:border-neutral-300 hover:text-neutral-900"
        }`}
      >
        <ThumbsUp size={16} />
      </button>
      <button
        type="button"
        disabled={!!submitted}
        onClick={() => submit("down")}
        aria-label="Thumbs down"
        className={`w-8 h-8 rounded-lg border flex items-center justify-center transition-all disabled:cursor-default ${
          submitted === "down"
            ? "bg-red-50 border-red-200 text-red-600"
            : "border-neutral-200 bg-white text-neutral-500 hover:bg-neutral-50 hover:border-neutral-300 hover:text-neutral-900"
        }`}
      >
        <ThumbsDown size={16} />
      </button>
    </div>
  );
}
