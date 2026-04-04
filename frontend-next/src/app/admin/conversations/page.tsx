// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useState } from "react";
import { fetchConversations } from "@/lib/chat/api";
import type { ConversationSummary } from "@/lib/chat/types";
import { ConversationTable } from "@/components/admin/conversation-table";

export default function ConversationsPage() {
  const [convos, setConvos] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchConversations(100)
      .then(setConvos)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-neutral-400 text-sm">Loading…</p>;

  return <ConversationTable conversations={convos} />;
}
