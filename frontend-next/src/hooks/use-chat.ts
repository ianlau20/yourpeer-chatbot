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

/** Wait ms milliseconds. */
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Try an async operation with one automatic retry after a delay.
 * Does NOT retry 429 (rate limit) or 403 (auth) errors.
 */
async function withRetry<T>(fn: () => Promise<T>, retryDelayMs = 1500): Promise<T> {
  try {
    return await fn();
  } catch (err: any) {
    const msg = err.message || "";
    // Don't retry rate limits or auth errors
    if (msg.includes("429") || msg.includes("403")) throw err;
    await delay(retryDelayMs);
    return fn();
  }
}

export function useChat() {
  const {
    sessionId,
    messages,
    isLoading,
    error,
    setSessionId,
    addMessage,
    removeMessage,
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
          const data = await withRetry(() => sendChatMessage("near me", sessionId, coords));
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
            text: msg.includes("wait") ? msg : "Sorry, something went wrong.",
            retryMessage: msg.includes("wait") ? undefined : GEOLOCATION_TRIGGER,
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
        // Auto-retry once with 1.5s backoff for transient failures (not 429/403)
        const data = await withRetry(() => sendChatMessage(message, sessionId, coords));
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
        // Rate-limit errors include timing info — show as-is, no retry.
        // Other errors get a Retry button via retryMessage.
        addMessage({
          id: nextMsgId(),
          role: "bot",
          text: msg.includes("wait") ? msg : "Sorry, something went wrong.",
          retryMessage: msg.includes("wait") ? undefined : message,
        });
      } finally {
        setLoading(false);
      }
    },
    [sessionId, latitude, longitude, hasCoords, addMessage, setSessionId, setLoading, setError, markQuickRepliesUsed, requestLocation],
  );

  /** Retry a failed message — removes the error and re-sends without
   *  adding a duplicate user message (the original is still in the chat). */
  const retry = useCallback(
    async (errorMsgId: string, originalText: string) => {
      removeMessage(errorMsgId);

      // Geolocation retry — re-run location request + API call
      if (originalText === GEOLOCATION_TRIGGER) {
        setLoading(true);
        const geoResult = hasCoords
          ? { latitude: latitude!, longitude: longitude! }
          : await requestLocation();

        if ("error" in geoResult) {
          setLoading(false);
          addMessage({
            id: nextMsgId(),
            role: "bot",
            text: geoResult.error,
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

        try {
          const data = await withRetry(() => sendChatMessage("near me", sessionId, geoResult));
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
            text: msg.includes("wait") ? msg : "Sorry, something went wrong.",
            retryMessage: msg.includes("wait") ? undefined : GEOLOCATION_TRIGGER,
          });
        } finally {
          setLoading(false);
        }
        return;
      }

      // Normal retry — API call only, user message is already in chat
      setLoading(true);
      try {
        const coords = hasCoords ? { latitude: latitude!, longitude: longitude! } : null;
        const data = await withRetry(() => sendChatMessage(originalText, sessionId, coords));
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
          text: msg.includes("wait") ? msg : "Sorry, something went wrong.",
          retryMessage: msg.includes("wait") ? undefined : originalText,
        });
      } finally {
        setLoading(false);
      }
    },
    [sessionId, latitude, longitude, hasCoords, addMessage, removeMessage, setSessionId, setLoading, setError, requestLocation],
  );

  const submitFeedback = useCallback(
    (rating: FeedbackRating) => {
      if (sessionId) sendFeedback(sessionId, rating);
    },
    [sessionId],
  );

  return { messages, isLoading, error, send, retry, submitFeedback };
}
