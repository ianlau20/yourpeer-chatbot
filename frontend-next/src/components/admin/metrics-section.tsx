// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

interface MetricsSectionProps {
  title: string;
  description?: string;
  children: React.ReactNode;
}

export function MetricsSection({ title, description, children }: MetricsSectionProps) {
  return (
    <div className="mb-9">
      <div className="text-xs font-bold uppercase tracking-widest text-neutral-400 mb-3 pb-2 border-b border-neutral-200">
        {title}
      </div>
      {description && (
        <p className="text-sm text-neutral-500 mb-4">{description}</p>
      )}
      {/* Header row */}
      <div className="grid grid-cols-[240px_1fr_130px_110px_90px] gap-3.5 pb-2 text-[0.7rem] uppercase tracking-wider text-neutral-400 font-semibold">
        <span>Metric</span>
        <span>Target</span>
        <span className="text-right">Current</span>
        <span className="text-right">Status</span>
        <span className="text-right">Phase</span>
      </div>
      {children}
    </div>
  );
}
