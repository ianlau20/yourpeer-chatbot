// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useCallback } from "react";
import { useChatStore, nextMsgId } from "@/lib/chat/store";
import { sendChatMessage, sendFeedback } from "@/lib/chat/api";
import type { FeedbackRating } from "@/lib/chat/types";

export function useChat() {
  const {
    sessionId,
    messages,
    isLoading,
    error,
    setSessionId,
    addMessage,
    setLoading,
    setError,
    markQuickRepliesUsed,
  } = useChatStore();

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message) return;

      // Mark any existing quick replies as used
      markQuickRepliesUsed();

      // Add user message immediately
      addMessage({ id: nextMsgId(), role: "user", text: message });

      setLoading(true);
      try {
        const data = await sendChatMessage(message, sessionId);
        if (data.session_id) setSessionId(data.session_id);

        addMessage({
          id: nextMsgId(),
          role: "bot",
          text: data.response || "(No response text)",
          services: data.services,
          quick_replies: data.quick_replies,
          showFeedback: (data.services?.length ?? 0) > 0,
        });
      } catch (err: any) {
        setError(`Error: ${err.message}`);
        addMessage({
          id: nextMsgId(),
          role: "bot",
          text: "Sorry, something went wrong. Please try again.",
        });
      } finally {
        setLoading(false);
      }
    },
    [sessionId, addMessage, setSessionId, setLoading, setError, markQuickRepliesUsed],
  );

  const submitFeedback = useCallback(
    (rating: FeedbackRating) => {
      if (sessionId) sendFeedback(sessionId, rating);
    },
    [sessionId],
  );

  return { messages, isLoading, error, send, submitFeedback };
}
