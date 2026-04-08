// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect } from "react";
import { useAdminStore } from "@/lib/admin/store";
import { QueryLogTable } from "@/components/admin/query-log-table";
import { TableSkeleton } from "@/components/admin/loading-skeleton";

export default function QueriesPage() {
  const { queries, fetchQueries } = useAdminStore();

  useEffect(() => {
    fetchQueries();
  }, [fetchQueries]);

  if (queries.loading && queries.data.length === 0) {
    return <TableSkeleton rows={6} cols={4} />;
  }

  return <QueryLogTable queries={queries.data} />;
}
