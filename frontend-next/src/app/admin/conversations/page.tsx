// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect } from "react";
import { useAdminStore } from "@/lib/admin/store";
import { ConversationTable } from "@/components/admin/conversation-table";
import { TableSkeleton } from "@/components/admin/loading-skeleton";

export default function ConversationsPage() {
  const { conversations, fetchConversations } = useAdminStore();

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  if (conversations.loading && conversations.data.length === 0) {
    return <TableSkeleton rows={6} cols={5} />;
  }

  return <ConversationTable conversations={conversations.data} />;
}
