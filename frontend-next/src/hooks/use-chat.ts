// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useCallback } from "react";
import { useChatStore, nextMsgId } from "@/lib/chat/store";
import { sendChatMessage, sendFeedback } from "@/lib/chat/api";
import { useGeolocation } from "./use-geolocation";
import type { FeedbackRating } from "@/lib/chat/types";

const GEOLOCATION_TRIGGER = "__use_geolocation__";

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

  const { latitude, longitude, hasCoords, requestLocation } = useGeolocation();

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message) return;

      // Mark any existing quick replies as used
      markQuickRepliesUsed();

      // Handle "Use my location" quick reply
      if (message === GEOLOCATION_TRIGGER) {
        addMessage({ id: nextMsgId(), role: "user", text: "Use my location" });
        setLoading(true);

        const coords = hasCoords
          ? { latitude: latitude!, longitude: longitude! }
          : await requestLocation();

        if (!coords) {
          // Permission denied or error — show message and let user pick borough
          setLoading(false);
          addMessage({
            id: nextMsgId(),
            role: "bot",
            text: "I wasn't able to get your location. Which borough or neighborhood are you in?",
            quick_replies: [
              { label: "Manhattan", value: "Manhattan" },
              { label: "Brooklyn", value: "Brooklyn" },
              { label: "Queens", value: "Queens" },
              { label: "Bronx", value: "Bronx" },
              { label: "Staten Island", value: "Staten Island" },
            ],
          });
          return;
        }

        // Got coords — send "near me" with coordinates attached
        try {
          const data = await sendChatMessage("near me", sessionId, coords);
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
          const msg = err.message || "Something went wrong";
          setError(`Error: ${msg}`);
          addMessage({
            id: nextMsgId(),
            role: "bot",
            text: msg.includes("wait") ? msg : "Sorry, something went wrong. Please try again.",
          });
        } finally {
          setLoading(false);
        }
        return;
      }

      // Normal message flow
      addMessage({ id: nextMsgId(), role: "user", text: message });

      setLoading(true);
      try {
        // Attach coords if we have them
        const coords = hasCoords ? { latitude: latitude!, longitude: longitude! } : null;
        const data = await sendChatMessage(message, sessionId, coords);
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
        const msg = err.message || "Something went wrong";
        setError(`Error: ${msg}`);
        addMessage({
          id: nextMsgId(),
          role: "bot",
          text: msg.includes("wait") ? msg : "Sorry, something went wrong. Please try again.",
        });
      } finally {
        setLoading(false);
      }
    },
    [sessionId, latitude, longitude, hasCoords, addMessage, setSessionId, setLoading, setError, markQuickRepliesUsed, requestLocation],
  );

  const submitFeedback = useCallback(
    (rating: FeedbackRating) => {
      if (sessionId) sendFeedback(sessionId, rating);
    },
    [sessionId],
  );

  return { messages, isLoading, error, send, submitFeedback };
}
