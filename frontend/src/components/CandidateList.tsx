import { AlertTriangle, FileImage, Type } from "lucide-react";

import type { WatermarkCandidate } from "../types/document";

interface CandidateListProps {
  candidates: WatermarkCandidate[];
  selectedIds: Set<string>;
  onToggle: (candidateId: string) => void;
}

function confidenceLabel(confidence: number): { label: string; className: string } {
  if (confidence >= 0.7) return { label: "High confidence", className: "bg-accent/10 text-accent" };
  if (confidence >= 0.4) return { label: "Medium confidence", className: "bg-warn/10 text-warn" };
  return { label: "Low confidence", className: "bg-ink/10 text-ink/60" };
}

export function CandidateList({ candidates, selectedIds, onToggle }: CandidateListProps) {
  if (candidates.length === 0) {
    return (
      <div className="mt-4 flex items-start gap-2 rounded-xl bg-ink/[0.03] p-4 text-sm text-ink/60">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
        <p>No watermark candidates were detected automatically. You can still select an area manually below if something's visible.</p>
      </div>
    );
  }

  return (
    <fieldset className="mt-4">
      <legend className="mb-2 text-sm font-medium text-ink">Detected watermark candidates</legend>
      <div className="space-y-2">
        {candidates.map((candidate) => {
          const badge = confidenceLabel(candidate.confidence);
          const TypeIcon = candidate.type === "image" ? FileImage : Type;
          const label = candidate.type === "image" ? candidate.text : `"${candidate.text}"`;
          return (
            <label
              key={candidate.candidate_id}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                selectedIds.has(candidate.candidate_id)
                  ? "border-accent/30 bg-accent/[0.04]"
                  : "border-ink/10 bg-white hover:border-accent/30"
              }`}
            >
              <input
                type="checkbox"
                checked={selectedIds.has(candidate.candidate_id)}
                onChange={() => onToggle(candidate.candidate_id)}
                className="mt-1 h-4 w-4 rounded border-ink/30 text-accent focus:ring-accent"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="flex min-w-0 items-center gap-1.5 truncate font-medium text-ink">
                    <TypeIcon className="h-3.5 w-3.5 shrink-0 text-ink/40" aria-hidden="true" />
                    <span className="truncate">{label}</span>
                  </p>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}>{badge.label}</span>
                </div>
                <p className="mt-0.5 text-xs text-ink/50">
                  Page {candidate.page} &middot; {candidate.reasons.join(", ")}
                </p>
              </div>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
