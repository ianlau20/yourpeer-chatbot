// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect } from "react";
import { useAdminStore } from "@/lib/admin/store";
import { QueryLogTable } from "@/components/admin/query-log-table";

export default function QueriesPage() {
  const { queries, fetchQueries } = useAdminStore();

  useEffect(() => {
    fetchQueries();
  }, [fetchQueries]);

  if (queries.loading && queries.data.length === 0) {
    return <p className="text-neutral-400 text-sm">Loading…</p>;
  }

  return <QueryLogTable queries={queries.data} />;
}
