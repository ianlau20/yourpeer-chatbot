// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

interface StatCardProps {
  label: string;
  value: string | number;
  note?: string | null;
  colorClass?: string;
}

export function StatCard({ label, value, note, colorClass }: StatCardProps) {
  return (
    <div className="bg-white border border-neutral-200 rounded-lg p-4">
      <div className="text-xs uppercase tracking-wider text-neutral-500 mb-1.5">
        {label}
        {note && (
          <span className="ml-1.5 text-[0.68rem] font-normal text-neutral-400">
            {note}
          </span>
        )}
      </div>
      <div className={`text-2xl font-bold tracking-tight ${colorClass || "text-neutral-900"}`}>
        {value ?? "—"}
      </div>
    </div>
  );
}
