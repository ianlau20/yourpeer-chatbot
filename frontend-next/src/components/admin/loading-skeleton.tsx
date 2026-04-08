// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

/**
 * Skeleton loading placeholders for admin pages.
 *
 * These provide visual structure while data loads, replacing plain
 * "Loading…" text with animated shapes that match the final layout.
 */

function Bone({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-neutral-200 ${className}`}
      aria-hidden="true"
    />
  );
}

/** Skeleton for StatCard grid (overview page). */
export function StatCardSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div
      className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3"
      role="status"
      aria-label="Loading statistics"
    >
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="bg-white border border-neutral-200 rounded-lg px-4 py-4"
        >
          <Bone className="h-3 w-20 mb-3" />
          <Bone className="h-7 w-14 mb-2" />
          <Bone className="h-2.5 w-24" />
        </div>
      ))}
    </div>
  );
}

/** Skeleton for table views (conversations, queries, events). */
export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div
      className="bg-white border border-neutral-200 rounded-lg overflow-hidden"
      role="status"
      aria-label="Loading table"
    >
      {/* Header */}
      <div className="flex gap-4 px-4 py-3 border-b border-neutral-200">
        {Array.from({ length: cols }).map((_, i) => (
          <Bone key={i} className="h-3 w-20" />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-4 px-4 py-3 border-b border-neutral-100">
          {Array.from({ length: cols }).map((_, c) => (
            <Bone
              key={c}
              className={`h-4 ${c === 0 ? "w-24" : "w-16"}`}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Skeleton for metrics page (sections with metric rows). */
export function MetricsSkeleton() {
  return (
    <div role="status" aria-label="Loading metrics">
      {[1, 2, 3].map((section) => (
        <div key={section} className="mb-6">
          <Bone className="h-5 w-40 mb-3" />
          <div className="bg-white border border-neutral-200 rounded-lg overflow-hidden">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex justify-between px-4 py-3 border-b border-neutral-100">
                <Bone className="h-4 w-36" />
                <Bone className="h-4 w-16" />
                <Bone className="h-4 w-20" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Skeleton for eval results page. */
export function EvalSkeleton() {
  return (
    <div role="status" aria-label="Loading evaluation results">
      <Bone className="h-5 w-48 mb-4" />
      <div className="bg-white border border-neutral-200 rounded-lg p-4 mb-4">
        <Bone className="h-4 w-64 mb-3" />
        <Bone className="h-4 w-52 mb-3" />
        <Bone className="h-4 w-40" />
      </div>
      <TableSkeleton rows={6} cols={5} />
    </div>
  );
}
