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

        if ("error" in coords) {
          // Permission denied, timeout, or unavailable — show specific reason
          setLoading(false);
          addMessage({
            id: nextMsgId(),
            role: "bot",
            text: coords.error,
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
          // Stale session token — clear and retry
          if (err.message?.includes("403") && sessionId) {
            try {
              useChatStore.getState().setSessionId(null);
              const data = await sendChatMessage("near me", null, coords);
              if (data.session_id) setSessionId(data.session_id);
              addMessage({
                id: nextMsgId(),
                role: "bot",
                text: data.response || "(No response text)",
                services: data.services,
                quick_replies: data.quick_replies,
                showFeedback: (data.services?.length ?? 0) > 0,
              });
              setLoading(false);
              return;
            } catch {
              // Fall through
            }
          }

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
        // If the backend rejected our session token (e.g. SECRET changed),
        // clear the stale sessionId and retry once with no session so the
        // backend mints a fresh token.
        if (err.message?.includes("403") && sessionId) {
          try {
            useChatStore.getState().setSessionId(null);
            const coords = hasCoords ? { latitude: latitude!, longitude: longitude! } : null;
            const data = await sendChatMessage(message, null, coords);
            if (data.session_id) setSessionId(data.session_id);
            addMessage({
              id: nextMsgId(),
              role: "bot",
              text: data.response || "(No response text)",
              services: data.services,
              quick_replies: data.quick_replies,
              showFeedback: (data.services?.length ?? 0) > 0,
            });
            setLoading(false);
            return;
          } catch {
            // Retry also failed — fall through to normal error handling
          }
        }

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
