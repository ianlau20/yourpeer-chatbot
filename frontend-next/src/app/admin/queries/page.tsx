// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useState } from "react";
import { fetchQueries } from "@/lib/chat/api";
import type { QueryLogEntry } from "@/lib/chat/types";
import { QueryLogTable } from "@/components/admin/query-log-table";

export default function QueriesPage() {
  const [queries, setQueries] = useState<QueryLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchQueries(200)
      .then(setQueries)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-neutral-400 text-sm">Loading…</p>;

  return <QueryLogTable queries={queries} />;
}
