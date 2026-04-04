// Copyright (c) 2024 Streetlives, Inc.
//
// Use of this source code is governed by an MIT-style
// license that can be found in the LICENSE file or at
// https://opensource.org/licenses/MIT.

"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchEvalResults } from "@/lib/chat/api";
import type { EvalReport } from "@/lib/chat/types";
import { EvalRunner, EvalResults } from "@/components/admin/eval-results";

export default function EvalsPage() {
  const [report, setReport] = useState<EvalReport | null | undefined>(undefined);

  const loadResults = useCallback(() => {
    fetchEvalResults()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  useEffect(() => {
    loadResults();
  }, [loadResults]);

  return (
    <>
      <EvalRunner onComplete={loadResults} />

      {report === undefined && (
        <p className="text-neutral-400 text-sm">Loading…</p>
      )}

      {report === null && (
        <div className="text-center py-16 text-neutral-400">
          <div className="text-3xl mb-3">🧪</div>
          <p>No evaluation results yet.</p>
          <p className="mt-2 font-mono text-xs text-amber-600 bg-neutral-50 inline-block px-4 py-2 rounded-lg">
            Use the Run Evals button above, or run: python tests/eval_llm_judge.py
            --output tests/eval_report.json
          </p>
        </div>
      )}

      {report && <EvalResults report={report} />}
    </>
  );
}
