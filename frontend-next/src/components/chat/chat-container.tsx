// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/hooks/use-chat";
import { useOnlineStatus } from "@/hooks/use-online-status";
import { useChatStore } from "@/lib/chat/store";
import { ChatMessage } from "./chat-message";
import { ChatInput } from "./chat-input";
import { ChatStatus } from "./chat-status";

export function ChatContainer() {
  const { messages, isLoading, error, send, retry, submitFeedback } = useChat();
  const isOnline = useOnlineStatus();
  const chatRef = useRef<HTMLDivElement>(null);

  // Wait for Zustand persist to finish rehydrating from localStorage.
  // On SSR and first client render this is false; it flips to true once
  // the store has loaded (or determined there's nothing to load).
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    // Already done (e.g. empty localStorage — synchronous)
    if (useChatStore.persist.hasHydrated()) {
      setHydrated(true);
      return;
    }
    // Async case — wait for the callback
    const unsub = useChatStore.persist.onFinishHydration(() => setHydrated(true));
    return unsub;
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    requestAnimationFrame(() => {
      if (chatRef.current) {
        chatRef.current.scrollTop = chatRef.current.scrollHeight;
      }
    });
  }, [messages]);

  return (
    <div className="flex flex-col max-w-[820px] mx-auto px-4 pb-7 min-h-dvh">
      <div className="flex items-baseline gap-2.5 px-1 pt-5 pb-3.5">
        <h1 className="text-xl font-bold tracking-tight text-neutral-900">
          YourPeer Chat
        </h1>
        <span className="text-sm text-neutral-400">
          Find services near you
        </span>
      </div>

      <div
        ref={chatRef}
        role="log"
        aria-label="Chat messages"
        aria-live="polite"
        aria-relevant="additions"
        tabIndex={0}
        className="flex-1 bg-white border border-neutral-200 rounded-2xl min-h-[400px] max-h-[75vh] overflow-y-auto p-5 flex flex-col gap-2.5 shadow-sm focus:outline-none focus:ring-2 focus:ring-amber-300/30"
      >
        {!hydrated ? (
          <p className="text-neutral-400 text-sm">Loading…</p>
        ) : (
          messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              onQuickReply={send}
              onFeedback={submitFeedback}
              onRetry={retry}
            />
          ))
        )}
      </div>

      {!isOnline && (
        <div
          role="alert"
          className="mx-1 my-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800"
        >
          You appear to be offline. Messages will fail until your connection is restored.
        </div>
      )}

      <ChatStatus isLoading={isLoading} error={error} />

      <ChatInput onSend={send} disabled={isLoading || !isOnline} />
    </div>
  );
}
