// Copyright (c) 2024 Streetlives, Inc.
// Use of this source code is governed by an MIT-style license.

import { useState, useMemo } from "react";

export type SortDir = "asc" | "desc";

export interface SortState<K extends string = string> {
  key: K;
  dir: SortDir;
}

/**
 * Generic hook for client-side table sorting.
 *
 * Usage:
 *   const { sorted, sortKey, sortDir, onSort } = useSortableTable(data, "timestamp", "desc");
 *   <SortableHeader label="Time" field="timestamp" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
 */
export function useSortableTable<T extends Record<string, unknown>>(
  data: T[],
  defaultKey: string,
  defaultDir: SortDir = "desc",
) {
  const [sort, setSort] = useState<SortState>({ key: defaultKey, dir: defaultDir });

  const onSort = (field: string) => {
    setSort((prev) => ({
      key: field,
      dir: prev.key === field && prev.dir === "desc" ? "asc" : "desc",
    }));
  };

  const sorted = useMemo(() => {
    const { key, dir } = sort;
    return [...data].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return dir === "asc" ? cmp : -cmp;
    });
  }, [data, sort]);

  return { sorted, sortKey: sort.key, sortDir: sort.dir, onSort };
}
