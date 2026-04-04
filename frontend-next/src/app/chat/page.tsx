// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

import type { Metadata } from "next";
import { ChatContainer } from "@/components/chat/chat-container";

export const metadata: Metadata = {
  title: "YourPeer Chat — Find services near you",
  description:
    "Chat with YourPeer to find free support services like food, shelter, showers, and more across NYC.",
};

export default function ChatPage() {
  return <ChatContainer />;
}
