import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileCheck2,
  Loader2,
  Lock,
  MousePointerSquareDashed,
  RotateCcw,
  ScanText,
  ShieldCheck,
  Sparkles,
  Wand2,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";

import { AnalysisSummary } from "../components/AnalysisSummary";
import { BeforeAfterView } from "../components/BeforeAfterView";
import { CandidateList } from "../components/CandidateList";
import { FeatureGrid } from "../components/FeatureGrid";
import { Footer } from "../components/Footer";
import { HowToUse } from "../components/HowToUse";
import { ImageWatermarkTool } from "../components/ImageWatermarkTool";
import { ManualSelectionCanvas } from "../components/ManualSelectionCanvas";
import { Navbar } from "../components/Navbar";
import { ProgressBar } from "../components/ProgressBar";
import { UploadArea } from "../components/UploadArea";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import { useDocumentUpload } from "../hooks/useDocumentUpload";
import { useManualRemoval } from "../hooks/useManualRemoval";
import { useOcr } from "../hooks/useOcr";
import { useWatermarkDetection } from "../hooks/useWatermarkDetection";
import { useWatermarkProcessing } from "../hooks/useWatermarkProcessing";
import { downloadUrl } from "../services/api";
import type { ManualRegion } from "../types/document";
import { formatFileSize, isImageFile } from "../utils/validateFile";

export function Home() {
  // ─── Track which file type was uploaded ────────────────────────────────
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [fileMode, setFileMode] = useState<"document" | "image" | null>(null);

  // ─── Document pipeline hooks (PDF / PPTX) ─────────────────────────────
  const { status, progress, result, errorMessage, upload, reset: resetUpload } = useDocumentUpload();
  const { status: analysisStatus, result: analysis, errorMessage: analysisError, progressMessage: analysisProgressMessage, progressPercent: analysisPercent, analyze, reset: resetAnalysis } = useDocumentAnalysis();
  const { status: detectionStatus, result: detection, errorMessage: detectionError, detect, reset: resetDetection } = useWatermarkDetection();
  const { status: processingStatus, result: processing, errorMessage: processingError, progressMessage: processingProgressMessage, progressPercent: processingPercent, process, reset: resetProcessing } = useWatermarkProcessing();
  const { status: manualStatus, result: manualResult, errorMessage: manualError, progressMessage: manualProgressMessage, progressPercent: manualPercent, remove: removeManual, reset: resetManual } = useManualRemoval();
  const { status: ocrStatus, result: ocrResult, errorMessage: ocrError, ocr, reset: resetOcr } = useOcr();

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showManualSelection, setShowManualSelection] = useState(false);

  // ─── Route file to the right pipeline ─────────────────────────────────
  const handleFileSelected = (file: File) => {
    setUploadedFile(file);
    if (isImageFile(file)) {
      setFileMode("image");
    } else {
      setFileMode("document");
      upload(file);
    }
  };

  // ─── Document pipeline automation ─────────────────────────────────────
  // Upload → Analyze → Detect automatically
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
      // Pre-select high-confidence candidates (>= 0.70)
      const highConf = detection.candidates.filter((c) => c.confidence >= 0.70);
      setSelectedIds(new Set(highConf.map((c) => c.candidate_id)));
    }
  }, [detectionStatus, detection]);

  // ─── Reset all state ──────────────────────────────────────────────────
  const reset = () => {
    resetUpload();
    resetAnalysis();
    resetDetection();
    resetProcessing();
    resetManual();
    resetOcr();
    setSelectedIds(new Set());
    setShowManualSelection(false);
    setUploadedFile(null);
    setFileMode(null);
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
    (ocrStatus === "success" && (ocrResult?.pages_ocred.length ?? 0) > 0) ||
    (detectionStatus === "success" && (detection?.candidates.length ?? 0) === 0);

  const isIdle = fileMode === null && (status === "idle" || status === "uploading");

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col font-sans selection:bg-brand-500 selection:text-white">
      {/* Top Navbar */}
      <Navbar />

      {/* Main Container */}
      <div className="mx-auto flex-1 w-full max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="mb-6 flex items-center justify-center gap-1.5 whitespace-nowrap text-xs font-medium text-slate-400 sm:gap-2">
          <a href="/" className="hover:text-brand-600 transition-colors">Home</a>
          <span>/</span>
          <span className="text-slate-700 font-semibold">Watermark Remover</span>
        </nav>

        {/* Hero Section */}
        <div className="mb-8 text-center space-y-4">
          <div className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3.5 py-1 text-xs font-semibold text-amber-700 border border-amber-200 shadow-sm">
            <Sparkles className="h-3.5 w-3.5 text-amber-500" />
            PDF &amp; PPTX &amp; IMAGE TOOLS • FREE ONLINE TOOL
          </div>

          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            Watermark Remover
          </h1>

          <p className="mx-auto max-w-2xl text-sm leading-relaxed text-slate-600 sm:text-base">
            AI-powered watermark detection and removal for PDFs, PowerPoint presentations, and images.
            Automatically detects text, logos, transparent overlays and corner badges.
          </p>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs font-semibold text-slate-600">
            <span className="inline-flex items-center gap-1.5 text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100">
              <ShieldCheck className="h-3.5 w-3.5" />
              100% Free
            </span>
            <span className="inline-flex items-center gap-1.5 text-brand-600 bg-brand-50 px-2.5 py-1 rounded-full border border-brand-100">
              <Lock className="h-3.5 w-3.5" />
              SSL Encrypted
            </span>
            <span className="inline-flex items-center gap-1.5 text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-full border border-indigo-100">
              <Zap className="h-3.5 w-3.5" />
              AI Auto-Detection
            </span>
            <span className="inline-flex items-center gap-1.5 text-purple-600 bg-purple-50 px-2.5 py-1 rounded-full border border-purple-100">
              <FileCheck2 className="h-3.5 w-3.5" />
              0 Tokens Used
            </span>
          </div>
        </div>

        {/* ─── Upload & Processing Area ──────────────────────────────────── */}
        <main className="mb-12">

          {/* ── UPLOAD AREA (idle or document uploading) ─────────────────── */}
          {isIdle ? (
            <div className="w-full">
              <UploadArea onFileSelected={handleFileSelected} disabled={status === "uploading"} />
              {status === "uploading" && (
                <div className="mt-6 rounded-2xl bg-white p-6 shadow-sm border border-slate-200">
                  <ProgressBar percent={progress} label={`Uploading document… ${progress}%`} />
                </div>
              )}
            </div>
          ) : null}

          {/* ── IMAGE WATERMARK TOOL ──────────────────────────────────────── */}
          {fileMode === "image" && uploadedFile ? (
            <ImageWatermarkTool file={uploadedFile} onReset={reset} />
          ) : null}

          {/* ── DOCUMENT PIPELINE (PDF / PPTX) ───────────────────────────── */}
          {fileMode === "document" && (
            <>
              {/* Upload Error */}
              {status === "error" && (
                <div className="rounded-3xl border border-red-200 bg-red-50/70 p-8 text-center shadow-md">
                  <p className="text-lg font-bold text-red-700">We couldn't upload this document</p>
                  <p className="mt-2 text-sm text-red-600 max-w-md mx-auto">{errorMessage}</p>
                  <button
                    type="button"
                    onClick={reset}
                    className="mt-5 inline-flex items-center gap-2 rounded-2xl bg-white px-5 py-2.5 text-sm font-semibold text-slate-800 shadow-sm border border-slate-200 hover:bg-slate-50 transition-all"
                  >
                    <RotateCcw className="h-4 w-4" />
                    Try Another Document
                  </button>
                </div>
              )}

              {/* Processing Card when document is uploaded */}
              {status === "success" && result && (
                <div className="rounded-3xl border border-slate-200 bg-white p-6 sm:p-8 shadow-xl shadow-brand-500/5">
                  {/* Document Overview */}
                  <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-100 pb-6">
                    <div className="flex items-center gap-3.5">
                      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 border border-brand-100">
                        <CheckCircle2 className="h-6 w-6" />
                      </div>
                      <div>
                        <h2 className="text-base font-bold text-slate-900">{result.original_filename}</h2>
                        <div className="flex items-center gap-3 text-xs text-slate-500 mt-1">
                          <span>{formatFileSize(result.size_bytes)}</span>
                          <span>•</span>
                          <span>{result.page_count ?? "—"} Pages / Slides</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <a
                        href={downloadUrl(result.document_id)}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white shadow-md shadow-emerald-600/20 hover:bg-emerald-700 transition-all"
                      >
                        <Download className="h-4 w-4" />
                        Download Document
                      </a>
                      <button
                        type="button"
                        onClick={reset}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-colors"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Upload New
                      </button>
                    </div>
                  </div>

                  {/* Analysis Loading */}
                  {analysisStatus === "analyzing" && (
                    <div className="mt-6 space-y-2">
                      <div className="flex items-center gap-3 rounded-2xl bg-brand-50/60 p-4 text-sm font-medium text-brand-700">
                        <Loader2 className="h-5 w-5 animate-spin shrink-0" />
                        <span className="truncate">{analysisProgressMessage ?? "Analyzing document structure & text objects…"}</span>
                      </div>
                      {analysisPercent > 0 && analysisPercent < 100 && (
                        <div className="px-1">
                          <ProgressBar percent={analysisPercent} label="" />
                        </div>
                      )}
                    </div>
                  )}

                  {/* Analysis Error */}
                  {analysisStatus === "error" && (
                    <div className="mt-6 rounded-2xl bg-red-50 p-4 text-sm text-red-600 border border-red-200 flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      Analysis failed: {analysisError}
                    </div>
                  )}

                  {/* Analysis Result */}
                  {analysisStatus === "success" && analysis && <AnalysisSummary analysis={analysis} />}

                  {/* Scanned Document OCR suggestion */}
                  {analysisStatus === "success" && analysis?.appears_scanned && ocrStatus !== "success" && (
                    <div className="mt-6 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-5">
                      <p className="text-sm font-bold text-indigo-950">Scanned Document Detected</p>
                      <p className="mt-1 text-xs leading-relaxed text-indigo-800/80">
                        This document appears to be a scan or photo. You can add an invisible searchable text layer with OCR while preserving 100% of the visual layout.
                      </p>
                      <button
                        type="button"
                        onClick={handleRunOcr}
                        disabled={ocrStatus === "running"}
                        className="mt-3 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 transition-all disabled:opacity-50"
                      >
                        {ocrStatus === "running" ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <ScanText className="h-4 w-4" />
                        )}
                        {ocrStatus === "running" ? "Reading document…" : "Make Document Searchable (OCR)"}
                      </button>
                      {ocrStatus === "error" && (
                        <p className="mt-2 text-xs text-red-600 font-medium">OCR failed: {ocrError}</p>
                      )}
                    </div>
                  )}

                  {/* Detection Status */}
                  {detectionStatus === "detecting" && (
                    <div className="mt-6 flex items-center gap-3 rounded-2xl bg-brand-50/60 p-4 text-sm font-medium text-brand-700">
                      <Loader2 className="h-5 w-5 animate-spin" />
                      Detecting watermark signatures (CamScanner, Gamma, Canva, Stamps)…
                    </div>
                  )}

                  {/* Detection Error */}
                  {detectionStatus === "error" && (
                    <div className="mt-6 rounded-2xl bg-red-50 p-4 text-sm text-red-600 border border-red-200 flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      Detection failed: {detectionError}
                    </div>
                  )}

                  {/* Detection Candidates */}
                  {detectionStatus === "success" && detection && processingStatus !== "success" && (
                    <div className="mt-6">
                      <CandidateList
                        candidates={detection.candidates}
                        selectedIds={selectedIds}
                        onToggle={toggleCandidate}
                      />

                      {detection.candidates.length > 0 && (
                        <div className="mt-5 space-y-3">
                          <button
                            type="button"
                            onClick={handleRemoveWatermarks}
                            disabled={selectedIds.size === 0 || processingStatus === "processing"}
                            className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-brand-600 to-brand-500 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-brand-500/25 hover:from-brand-700 hover:to-brand-600 hover:scale-[1.01] transition-all disabled:opacity-50 disabled:scale-100"
                          >
                            {processingStatus === "processing" ? (
                              <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                              <Wand2 className="h-4 w-4" />
                            )}
                            Remove {selectedIds.size} Selected Watermark{selectedIds.size === 1 ? "" : "s"}
                          </button>

                          {/* Live processing progress */}
                          {processingStatus === "processing" && (
                            <div className="space-y-1.5">
                              <p className="text-xs text-brand-600 font-medium truncate">
                                {processingProgressMessage ?? "Removing watermarks…"}
                              </p>
                              {processingPercent > 0 && processingPercent < 100 && (
                                <ProgressBar percent={processingPercent} label="" />
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Processing Error */}
                  {processingStatus === "error" && (
                    <div className="mt-6 rounded-2xl bg-red-50 p-4 text-sm text-red-600 border border-red-200 flex items-center gap-2">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {processingError}
                    </div>
                  )}

                  {/* Processing Success Alert */}
                  {processingStatus === "success" && processing && (
                    <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5">
                      <p className="text-sm font-bold text-emerald-900">Watermark Removal Complete!</p>
                      {processing.skipped_candidate_ids.length > 0 ? (
                        <p className="mt-1 text-xs text-amber-800">
                          Processed {processing.pages_affected.length} page(s)/slide(s), but {processing.skipped_candidate_ids.length} selected candidate(s) could not be fully removed. Watermarks on shared slide masters or layouts can only be removed when all slides are selected.
                        </p>
                      ) : (
                        <p className="mt-1 text-xs text-emerald-700">
                          Successfully removed {processing.removed_count} watermark{processing.removed_count === 1 ? "" : "s"} across {processing.pages_affected.length} page(s)/slide(s).
                        </p>
                      )}
                    </div>
                  )}

                  {/* Manual Selection Fallback */}
                  {result.page_count !== null && (
                    <div className="mt-6 border-t border-slate-100 pt-6">
                      {!showManualSelection ? (
                        <button
                          type="button"
                          onClick={() => setShowManualSelection(true)}
                          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-all"
                        >
                          <MousePointerSquareDashed className="h-4 w-4 text-slate-500" />
                          Still see a watermark? Select area manually
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

                      {/* Live manual progress */}
                      {manualStatus === "removing" && (
                        <div className="mt-3 space-y-1.5">
                          <p className="text-xs text-brand-600 font-medium truncate">
                            {manualProgressMessage ?? "Applying manual removal…"}
                          </p>
                          {manualPercent > 0 && manualPercent < 100 && (
                            <ProgressBar percent={manualPercent} label="" />
                          )}
                        </div>
                      )}

                      {manualStatus === "error" && (
                        <div className="mt-3 rounded-xl bg-red-50 p-3 text-xs text-red-600 border border-red-200 flex items-center gap-1.5">
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                          {manualError}
                        </div>
                      )}

                      {manualStatus === "success" && manualResult && (
                        <div className="mt-3 rounded-xl bg-emerald-50 p-3 text-xs text-emerald-800 border border-emerald-200">
                          Removed {manualResult.regions_applied} manually selected area(s) across {manualResult.pages_affected.length} page(s).
                        </div>
                      )}
                    </div>
                  )}

                  {/* Before/After View */}
                  {hasCleanedResult && result.page_count !== null && (
                    <div className="mt-6">
                      <BeforeAfterView documentId={result.document_id} pageCount={result.page_count} />
                    </div>
                  )}

                  {/* Download CTA — Always visible when document is ready */}
                  <div className="mt-8 border-t border-slate-100 pt-6 flex flex-wrap items-center gap-4">
                    <a
                      href={downloadUrl(result.document_id)}
                      className="inline-flex items-center gap-2.5 rounded-2xl bg-gradient-to-r from-emerald-600 to-emerald-500 px-7 py-3.5 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 hover:from-emerald-700 hover:to-emerald-600 hover:scale-[1.01] transition-all"
                    >
                      <Download className="h-5 w-5" />
                      Download Cleaned Document
                    </a>

                    <button
                      type="button"
                      onClick={reset}
                      className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all"
                    >
                      <RotateCcw className="h-4 w-4" />
                      Clean Another File
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </main>

        {/* Feature Cards */}
        <FeatureGrid />

        {/* How To Use */}
        <HowToUse />
      </div>

      {/* Footer */}
      <Footer />
    </div>
  );
}
