import { CheckCircle2, Download, Loader2, MousePointerSquareDashed, RotateCcw, ScanText, ShieldCheck, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";

import { AnalysisSummary } from "../components/AnalysisSummary";
import { CandidateList } from "../components/CandidateList";
import { ManualSelectionCanvas } from "../components/ManualSelectionCanvas";
import { ProgressBar } from "../components/ProgressBar";
import { UploadArea } from "../components/UploadArea";
import { downloadUrl } from "../services/api";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import { useDocumentUpload } from "../hooks/useDocumentUpload";
import { useManualRemoval } from "../hooks/useManualRemoval";
import { useOcr } from "../hooks/useOcr";
import { useWatermarkDetection } from "../hooks/useWatermarkDetection";
import { useWatermarkProcessing } from "../hooks/useWatermarkProcessing";
import type { ManualRegion } from "../types/document";
import { formatFileSize } from "../utils/validateFile";

export function Home() {
  const { status, progress, result, errorMessage, upload, reset: resetUpload } = useDocumentUpload();
  const { status: analysisStatus, result: analysis, errorMessage: analysisError, analyze, reset: resetAnalysis } = useDocumentAnalysis();
  const { status: detectionStatus, result: detection, errorMessage: detectionError, detect, reset: resetDetection } = useWatermarkDetection();
  const { status: processingStatus, result: processing, errorMessage: processingError, process, reset: resetProcessing } = useWatermarkProcessing();
  const { status: manualStatus, result: manualResult, errorMessage: manualError, remove: removeManual, reset: resetManual } = useManualRemoval();
  const { status: ocrStatus, result: ocrResult, errorMessage: ocrError, ocr, reset: resetOcr } = useOcr();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showManualSelection, setShowManualSelection] = useState(false);

  // Workflow: Upload -> Validate -> Analyze -> Detect. Each step
  // kicks off automatically once the previous one succeeds.
  useEffect(() => {
    if (status === "success" && result) {
      analyze(result.document_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, result]);

  useEffect(() => {
    if (analysisStatus === "success" && result) {
      detect(result.document_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisStatus, result]);

  useEffect(() => {
    if (detectionStatus === "success" && detection) {
      // Pre-select every detected candidate; the user can uncheck
      // any before confirming removal — nothing is auto-removed.
      setSelectedIds(new Set(detection.candidates.map((c) => c.candidate_id)));
    }
  }, [detectionStatus, detection]);

  const reset = () => {
    resetUpload();
    resetAnalysis();
    resetDetection();
    resetProcessing();
    resetManual();
    resetOcr();
    setSelectedIds(new Set());
    setShowManualSelection(false);
  };

  const toggleCandidate = (candidateId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  };

  const handleRemoveWatermarks = () => {
    if (result && selectedIds.size > 0) {
      process(result.document_id, Array.from(selectedIds));
    }
  };

  const handleManualSubmit = (regions: ManualRegion[], applyToAllPages: boolean) => {
    if (result) {
      removeManual(result.document_id, regions, applyToAllPages);
    }
  };

  const handleRunOcr = () => {
    if (result) {
      ocr(result.document_id);
    }
  };

  const hasCleanedResult =
    processingStatus === "success" ||
    manualStatus === "success" ||
    (ocrStatus === "success" && (ocrResult?.pages_ocred.length ?? 0) > 0);

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col px-6 py-16">
      <header className="mb-12 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1 text-xs font-medium text-accent">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Private document processing
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Remove watermarks from your documents</h1>
        <p className="mt-3 text-ink/60">Upload &rarr; Detect &rarr; Review &rarr; Clean. Files are processed locally and deleted automatically.</p>
      </header>

      <main className="flex-1">
        {status === "idle" || status === "uploading" ? (
          <>
            <UploadArea onFileSelected={upload} disabled={status === "uploading"} />
            {status === "uploading" && (
              <div className="mt-6">
                <ProgressBar percent={progress} label={`Uploading… ${progress}%`} />
              </div>
            )}
          </>
        ) : null}

        {status === "error" && (
          <div className="mt-6 rounded-2xl border border-warn/20 bg-warn/5 p-6 shadow-sm">
            <p className="font-medium text-warn">We couldn't upload this document.</p>
            <p className="mt-1 text-sm text-ink/70">{errorMessage}</p>
            <button
              type="button"
              onClick={reset}
              className="mt-4 inline-flex items-center gap-2 rounded-xl border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Try another file
            </button>
          </div>
        )}

        {status === "success" && result && (
          <div className="mt-6 rounded-2xl border border-accent/20 bg-accent/[0.04] p-6 shadow-sm">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
              <div>
                <p className="font-medium text-ink">Uploaded successfully</p>
                <dl className="mt-2 space-y-1 text-sm text-ink/70">
                  <div className="flex gap-2">
                    <dt className="text-ink/50">File:</dt>
                    <dd>{result.original_filename}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Size:</dt>
                    <dd>{formatFileSize(result.size_bytes)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Pages:</dt>
                    <dd>{result.page_count ?? "—"}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Document ID:</dt>
                    <dd className="font-mono text-xs">{result.document_id}</dd>
                  </div>
                </dl>
              </div>
            </div>

            {analysisStatus === "analyzing" && (
              <div className="mt-4 flex items-center gap-2 text-sm text-ink/60">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Analyzing document…
              </div>
            )}

            {analysisStatus === "error" && (
              <div className="mt-4 rounded-xl bg-warn/5 p-3 text-sm text-warn">Analysis failed: {analysisError}</div>
            )}

            {analysisStatus === "success" && analysis && <AnalysisSummary analysis={analysis} />}

            {analysisStatus === "success" && analysis?.appears_scanned && ocrStatus !== "success" && (
              <div className="mt-4 rounded-xl border border-ink/10 bg-white p-4">
                <p className="text-sm font-medium text-ink">This document looks scanned</p>
                <p className="mt-1 text-xs text-ink/50">
                  Its text isn't selectable or searchable yet. Run OCR to add a searchable text layer —
                  the page will look exactly the same.
                </p>
                <button
                  type="button"
                  onClick={handleRunOcr}
                  disabled={ocrStatus === "running"}
                  className="mt-3 inline-flex items-center gap-2 rounded-xl border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {ocrStatus === "running" ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <ScanText className="h-4 w-4" aria-hidden="true" />
                  )}
                  Make this document searchable (OCR)
                </button>
                {ocrStatus === "error" && <p className="mt-2 text-sm text-warn">OCR failed: {ocrError}</p>}
              </div>
            )}

            {ocrStatus === "success" && ocrResult && (
              <div className="mt-4 rounded-xl border border-accent/20 bg-white p-4">
                {ocrResult.pages_ocred.length > 0 ? (
                  <>
                    <p className="text-sm font-medium text-ink">Document is now searchable</p>
                    <p className="mt-1 text-xs text-ink/50">
                      {ocrResult.pages_ocred.reduce((sum, p) => sum + p.words_added, 0)} words recognized across{" "}
                      {ocrResult.pages_ocred.length} page{ocrResult.pages_ocred.length === 1 ? "" : "s"}.
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-ink/60">This document is already searchable — no OCR was needed.</p>
                )}
              </div>
            )}

            {detectionStatus === "detecting" && (
              <div className="mt-4 flex items-center gap-2 text-sm text-ink/60">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Scanning for watermarks…
              </div>
            )}

            {detectionStatus === "error" && (
              <div className="mt-4 rounded-xl bg-warn/5 p-3 text-sm text-warn">Detection failed: {detectionError}</div>
            )}

            {detectionStatus === "success" && detection && processingStatus !== "success" && (
              <>
                <CandidateList candidates={detection.candidates} selectedIds={selectedIds} onToggle={toggleCandidate} />

                {detection.candidates.length > 0 && (
                  <button
                    type="button"
                    onClick={handleRemoveWatermarks}
                    disabled={selectedIds.size === 0 || processingStatus === "processing"}
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {processingStatus === "processing" ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      <Wand2 className="h-4 w-4" aria-hidden="true" />
                    )}
                    Remove selected watermark{selectedIds.size === 1 ? "" : "s"}
                  </button>
                )}
              </>
            )}

            {processingStatus === "error" && (
              <div className="mt-4 rounded-xl bg-warn/5 p-3 text-sm text-warn">Removal failed: {processingError}</div>
            )}

            {processingStatus === "success" && processing && (
              <div className="mt-4 rounded-xl border border-accent/20 bg-white p-4">
                <p className="text-sm font-medium text-ink">
                  Removed {processing.removed_count} of {processing.requested_count} selected watermark
                  {processing.requested_count === 1 ? "" : "s"}
                </p>
                <p className="mt-1 text-xs text-ink/50">Pages affected: {processing.pages_affected.join(", ") || "none"}</p>
              </div>
            )}

            {/* Manual selection is always available once a document is
                uploaded — it's the fallback for anything automatic
                detection structurally can't see, like a vector-drawn
                logo rather than an embedded image. */}
            {result.page_count !== null && (
              <div className="mt-4">
                {!showManualSelection ? (
                  <button
                    type="button"
                    onClick={() => setShowManualSelection(true)}
                    className="inline-flex items-center gap-2 rounded-xl border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <MousePointerSquareDashed className="h-4 w-4" aria-hidden="true" />
                    Still see a watermark? Select it manually
                  </button>
                ) : (
                  <ManualSelectionCanvas
                    documentId={result.document_id}
                    pageCount={result.page_count}
                    scannedPages={
                      new Set((analysis?.pages ?? []).filter((p) => p.is_scanned).map((p) => p.page_number))
                    }
                    onSubmit={handleManualSubmit}
                    isSubmitting={manualStatus === "removing"}
                  />
                )}

                {manualStatus === "error" && (
                  <div className="mt-3 rounded-xl bg-warn/5 p-3 text-sm text-warn">Removal failed: {manualError}</div>
                )}

                {manualStatus === "success" && manualResult && (
                  <div className="mt-3 rounded-xl border border-accent/20 bg-white p-4">
                    <p className="text-sm font-medium text-ink">
                      Removed {manualResult.regions_applied} manually selected area{manualResult.regions_applied === 1 ? "" : "s"}
                    </p>
                    <p className="mt-1 text-xs text-ink/50">Pages affected: {manualResult.pages_affected.join(", ") || "none"}</p>
                  </div>
                )}
              </div>
            )}

            {hasCleanedResult && (
              <a
                href={downloadUrl(result.document_id)}
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                Download cleaned PDF
              </a>
            )}

            <div>
              <button
                type="button"
                onClick={reset}
                className="mt-4 inline-flex items-center gap-2 rounded-xl border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                Upload another document
              </button>
            </div>
          </div>
        )}
      </main>

      <footer className="mt-16 text-center text-xs text-ink/40">
        For documents you own or are authorized to modify. Files are deleted automatically after processing.
      </footer>
    </div>
  );
}
