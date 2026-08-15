import { FileWarning, Image as ImageIcon, ScanLine, Type } from "lucide-react";

import type { DocumentAnalysisResponse } from "../types/document";

interface AnalysisSummaryProps {
  analysis: DocumentAnalysisResponse;
}

export function AnalysisSummary({ analysis }: AnalysisSummaryProps) {
  return (
    <div className="mt-4 rounded-xl border border-ink/10 bg-white p-5">
      <p className="mb-3 text-sm font-medium text-ink">Document analysis</p>

      <div className="grid grid-cols-3 gap-3 text-center">
        <div className="rounded-lg bg-ink/[0.03] p-3">
          <Type className="mx-auto h-4 w-4 text-ink/40" aria-hidden="true" />
          <p className="mt-1 text-lg font-semibold text-ink">{analysis.total_text_objects}</p>
          <p className="text-xs text-ink/50">text objects</p>
        </div>
        <div className="rounded-lg bg-ink/[0.03] p-3">
          <ImageIcon className="mx-auto h-4 w-4 text-ink/40" aria-hidden="true" />
          <p className="mt-1 text-lg font-semibold text-ink">{analysis.total_images}</p>
          <p className="text-xs text-ink/50">images</p>
        </div>
        <div className="rounded-lg bg-ink/[0.03] p-3">
          <ScanLine className="mx-auto h-4 w-4 text-ink/40" aria-hidden="true" />
          <p className="mt-1 text-lg font-semibold text-ink">{analysis.appears_scanned ? "Yes" : "No"}</p>
          <p className="text-xs text-ink/50">appears scanned</p>
        </div>
      </div>

      {analysis.appears_scanned && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-warn/5 p-3 text-sm text-warn">
          <FileWarning className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>This document looks like a scanned image rather than searchable text. Watermark removal for scanned pages arrives in a later phase.</p>
        </div>
      )}

      <p className="mt-3 text-xs text-ink/40">
        Watermark detection isn't implemented yet — this is Phase 2 (structural analysis only).
      </p>
    </div>
  );
}
