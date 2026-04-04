// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import { create } from "zustand";
import type { ChatMessage, QuickReply } from "./types";

interface ChatStore {
  sessionId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;

  setSessionId: (id: string) => void;
  addMessage: (msg: ChatMessage) => void;
  setLoading: (v: boolean) => void;
  setError: (msg: string | null) => void;
  markQuickRepliesUsed: () => void;
  resetChat: () => void;
}

let msgCounter = 0;
export function nextMsgId(): string {
  return `msg-${++msgCounter}-${Date.now()}`;
}

const WELCOME_MESSAGE =
  "Hi, welcome to YourPeer. I can help you find services like food, shelter, showers, and more in your area. Your conversation is private — I don't save your name or personal details. You can stop or start over anytime.\n\nWhat are you looking for today?";

const INITIAL_QUICK_REPLIES: QuickReply[] = [
  { label: "🍽️ Food", value: "I need food" },
  { label: "🏠 Shelter", value: "I need shelter" },
  { label: "🚿 Showers", value: "I need a shower" },
  { label: "👕 Clothing", value: "I need clothing" },
  { label: "🏥 Health Care", value: "I need health care" },
  { label: "💼 Jobs", value: "I need help finding a job" },
  { label: "⚖️ Legal Help", value: "I need legal help" },
  { label: "🧠 Mental Health", value: "I need mental health support" },
  { label: "📋 Other", value: "I need other services" },
];

function makeWelcomeMessage(): ChatMessage {
  return {
    id: nextMsgId(),
    role: "bot",
    text: WELCOME_MESSAGE,
    quick_replies: INITIAL_QUICK_REPLIES,
  };
}

export const useChatStore = create<ChatStore>((set) => ({
  sessionId: null,
  messages: [makeWelcomeMessage()],
  isLoading: false,
  error: null,

  setSessionId: (id) => set({ sessionId: id }),

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  setLoading: (v) => set({ isLoading: v, error: v ? null : undefined }),

  setError: (msg) => set({ error: msg }),

  markQuickRepliesUsed: () =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.quick_replies ? { ...m, quick_replies: undefined } : m,
      ),
    })),

  resetChat: () =>
    set({
      sessionId: null,
      messages: [makeWelcomeMessage()],
      isLoading: false,
      error: null,
    }),
}));
