/**
 * ImageWatermarkTool — the complete image watermark detection + removal UI.
 *
 * Stages:
 *   idle      → show upload area (already handled by parent, this receives a File)
 *   detecting → spinner "AI is analyzing…"
 *   detected  → annotated preview + candidate list + action buttons
 *   removing  → spinner "Removing watermarks…"
 *   done      → before/after view + download button
 *   error     → error message + retry button
 */
import {
  AlertCircle,
  Check,
  CheckSquare,
  Download,
  Eraser,
  Loader2,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  Square,
  Wand2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useImageWatermark } from "../hooks/useImageWatermark";
import type { ImageDetectionResult } from "../types/document";
import { formatFileSize } from "../utils/validateFile";

interface ImageWatermarkToolProps {
  file: File;
  onReset: () => void;
}

// ─── Confidence helpers ───────────────────────────────────────────────────────

function confidenceBadge(conf: number): { text: string; cls: string } {
  if (conf >= 0.70) return { text: `${Math.round(conf * 100)}% — High`, cls: "bg-emerald-100 text-emerald-800 border-emerald-200" };
  if (conf >= 0.40) return { text: `${Math.round(conf * 100)}% — Medium`, cls: "bg-amber-100 text-amber-800 border-amber-200" };
  return { text: `${Math.round(conf * 100)}% — Low`, cls: "bg-slate-100 text-slate-600 border-slate-200" };
}

function typeLabel(type: string): string {
  return (
    {
      text: "Text",
      logo: "Logo",
      overlay: "Overlay",
      pattern: "Pattern",
      transparent_overlay: "Transparent",
    }[type] ?? type
  );
}

// ─── Manual bbox draw overlay ─────────────────────────────────────────────────

interface ManualBboxDrawProps {
  imageUrl: string;
  imageW: number;
  imageH: number;
  onAddBbox: (bbox: { x: number; y: number; width: number; height: number }) => void;
  existingBboxes: Array<{ id: string; x: number; y: number; width: number; height: number }>;
  aiDetections: ImageDetectionResult[];
  selectedIds: Set<string>;
  onRemoveId: (id: string) => void;
}

function ManualBboxDraw({
  imageUrl,
  imageW,
  imageH,
  onAddBbox,
  existingBboxes,
  aiDetections,
  selectedIds,
  onRemoveId,
}: ManualBboxDrawProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [dragCurr, setDragCurr] = useState<{ x: number; y: number } | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!dragStart) return;

    const getPoint = (cx: number, cy: number) => {
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0 || rect.height === 0) return null;
      return {
        x: Math.min(Math.max((cx - rect.left) / rect.width, 0), 1),
        y: Math.min(Math.max((cy - rect.top) / rect.height, 0), 1),
      };
    };

    const onMove = (e: MouseEvent) => {
      const pt = getPoint(e.clientX, e.clientY);
      if (pt) setDragCurr(pt);
    };
    const onUp = (e: MouseEvent) => {
      const pt = getPoint(e.clientX, e.clientY) ?? dragCurr;
      if (pt && dragStart) {
        const fx0 = Math.min(dragStart.x, pt.x);
        const fy0 = Math.min(dragStart.y, pt.y);
        const fx1 = Math.max(dragStart.x, pt.x);
        const fy1 = Math.max(dragStart.y, pt.y);
        if ((fx1 - fx0) > 0.005 && (fy1 - fy0) > 0.005) {
          onAddBbox({
            x: Math.round(fx0 * imageW),
            y: Math.round(fy0 * imageH),
            width: Math.round((fx1 - fx0) * imageW),
            height: Math.round((fy1 - fy0) * imageH),
          });
        }
      }
      setDragStart(null);
      setDragCurr(null);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragStart, dragCurr, onAddBbox, imageW, imageH]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!loaded) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setDragStart({
      x: Math.max(0, Math.min((e.clientX - rect.left) / rect.width, 1)),
      y: Math.max(0, Math.min((e.clientY - rect.top) / rect.height, 1)),
    });
    setDragCurr(null);
  };

  const dragRect =
    dragStart && dragCurr
      ? {
          x0: Math.min(dragStart.x, dragCurr.x),
          y0: Math.min(dragStart.y, dragCurr.y),
          x1: Math.max(dragStart.x, dragCurr.x),
          y1: Math.max(dragStart.y, dragCurr.y),
        }
      : null;

  return (
    <div
      ref={containerRef}
      className="relative w-full cursor-crosshair select-none overflow-hidden rounded-xl border border-slate-200 bg-slate-50"
      style={{ maxHeight: "60vh" }}
      onMouseDown={handleMouseDown}
    >
      {!loaded && (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      )}
      <div className={`relative inline-block w-full ${loaded ? "" : "hidden"}`}>
        <img
          src={imageUrl}
          alt="Image preview"
          className="block w-full"
          draggable={false}
          onLoad={() => setLoaded(true)}
        />

        {/* AI detection overlays */}
        {aiDetections
          .filter((d) => selectedIds.has(d.detection_id))
          .map((d) => (
            <div
              key={d.detection_id}
              className="absolute border-2 border-blue-500 bg-blue-500/10"
              style={{
                left: `${(d.bbox.x / imageW) * 100}%`,
                top: `${(d.bbox.y / imageH) * 100}%`,
                width: `${(d.bbox.width / imageW) * 100}%`,
                height: `${(d.bbox.height / imageH) * 100}%`,
              }}
            />
          ))}

        {/* Manual bbox overlays */}
        {existingBboxes
          .filter((b) => selectedIds.has(b.id))
          .map((b) => (
            <div
              key={b.id}
              className="absolute border-2 border-amber-500 bg-amber-500/10"
              style={{
                left: `${(b.x / imageW) * 100}%`,
                top: `${(b.y / imageH) * 100}%`,
                width: `${(b.width / imageW) * 100}%`,
                height: `${(b.height / imageH) * 100}%`,
              }}
            />
          ))}

        {/* Active drag rect */}
        {dragRect && (
          <div
            className="pointer-events-none absolute border-2 border-dashed border-amber-400 bg-amber-400/10"
            style={{
              left: `${dragRect.x0 * 100}%`,
              top: `${dragRect.y0 * 100}%`,
              width: `${(dragRect.x1 - dragRect.x0) * 100}%`,
              height: `${(dragRect.y1 - dragRect.y0) * 100}%`,
            }}
          />
        )}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ImageWatermarkTool({ file, onReset }: ImageWatermarkToolProps) {
  const {
    stage,
    previewUrl,
    annotatedPreviewUrl,
    resultUrl,
    resultBlob,
    detection,
    selectedIds,
    errorMessage,
    uploadProgress,
    startWithFile,
    toggleSelection,
    selectAll,
    deselectAll,
    addManualBbox,
    removeById,
    confirmRemoval,
    scanAgain,
    reset,
  } = useImageWatermark();

  const [showMaskEditor, setShowMaskEditor] = useState(false);
  const [manualBboxes, setManualBboxes] = useState<
    Array<{ id: string; x: number; y: number; width: number; height: number }>
  >([]);

  // Auto-start detection on mount
  useEffect(() => {
    startWithFile(file);
  }, [file, startWithFile]);

  const handleReset = () => {
    reset();
    onReset();
  };

  const handleAddBbox = (bbox: { x: number; y: number; width: number; height: number }) => {
    const id = `manual_${Date.now()}`;
    const entry = { id, ...bbox };
    setManualBboxes((prev) => [...prev, entry]);
    addManualBbox(bbox);
  };

  const handleRemoveBbox = (id: string) => {
    setManualBboxes((prev) => prev.filter((b) => b.id !== id));
    removeById(id);
  };

  const imageW = detection?.image_width ?? 1;
  const imageH = detection?.image_height ?? 1;

  // Download helper
  const handleDownload = () => {
    if (!resultBlob) return;
    const url = URL.createObjectURL(resultBlob);
    const a = document.createElement("a");
    a.href = url;
    const ext = file.name.split(".").pop() || "jpg";
    a.download = `cleaned_${file.name.replace(/\.[^.]+$/, "")}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ─── Detecting stage ────────────────────────────────────────────────────
  if (stage === "detecting") {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3 text-sm font-medium text-brand-700">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>
            AI is analyzing your image for watermarks…{" "}
            {uploadProgress > 0 && uploadProgress < 100 ? `(${uploadProgress}% uploaded)` : ""}
          </span>
        </div>
        <div className="mt-3 text-xs text-slate-500">
          Checking for text, logos, transparent overlays, corner badges and repeating patterns.
        </div>
      </div>
    );
  }

  // ─── Error stage ─────────────────────────────────────────────────────────
  if (stage === "error") {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50/70 p-6 text-center shadow-sm">
        <AlertCircle className="mx-auto mb-2 h-8 w-8 text-red-500" />
        <p className="font-bold text-red-800">Detection failed</p>
        <p className="mt-1 text-sm text-red-600">{errorMessage}</p>
        <div className="mt-4 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            onClick={() => startWithFile(file)}
            className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 transition-all"
          >
            <RefreshCw className="h-4 w-4" />
            Try Again
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all"
          >
            <RotateCcw className="h-4 w-4" />
            Upload Different Image
          </button>
        </div>
      </div>
    );
  }

  // ─── Done stage ───────────────────────────────────────────────────────────
  if (stage === "done" && resultUrl) {
    return (
      <div className="space-y-6">
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-5">
          <p className="font-bold text-emerald-900">✓ Watermark Removed Successfully!</p>
          <p className="mt-1 text-sm text-emerald-700">
            Your image has been cleaned. Click below to download.
          </p>
        </div>

        {/* Before / After */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Before</p>
            <img
              src={previewUrl ?? ""}
              alt="Before removal"
              className="w-full rounded-xl border border-slate-200 shadow-sm"
            />
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">After</p>
            <img
              src={resultUrl}
              alt="After removal"
              className="w-full rounded-xl border border-slate-200 shadow-sm"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-emerald-600 to-emerald-500 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-emerald-500/25 hover:from-emerald-700 hover:to-emerald-600 transition-all"
          >
            <Download className="h-4 w-4" />
            Download Cleaned Image
          </button>
          <button
            type="button"
            onClick={() => { reset(); startWithFile(file); }}
            className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all"
          >
            <ScanSearch className="h-4 w-4" />
            Remove More Watermarks
          </button>
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all"
          >
            <RotateCcw className="h-4 w-4" />
            New Image
          </button>
        </div>
      </div>
    );
  }

  // ─── Detected / Removing stages ───────────────────────────────────────────
  const isRemoving = stage === "removing";
  const detections = detection?.detections ?? [];
  const highConf = detections.filter((d) => d.confidence >= 0.70);
  const medConf  = detections.filter((d) => d.confidence >= 0.40 && d.confidence < 0.70);
  const lowConf  = detections.filter((d) => d.confidence < 0.40);

  return (
    <div className="space-y-5">
      {/* Detection status header */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="font-bold text-slate-900">
              {detections.length === 0
                ? "No watermarks automatically detected"
                : `${detections.length} possible watermark${detections.length === 1 ? "" : "s"} detected`}
            </p>
            <p className="mt-0.5 text-sm text-slate-500">{detection?.message}</p>
            <p className="mt-0.5 text-xs text-slate-400">
              {file.name} • {formatFileSize(file.size)} •{" "}
              {imageW}×{imageH}px
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={scanAgain}
              disabled={isRemoving}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-all disabled:opacity-50"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Scan Again
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={isRemoving}
              className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 transition-all disabled:opacity-50"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Upload New
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Left: Preview */}
        <div>
          <p className="mb-2 text-sm font-semibold text-slate-700">
            {annotatedPreviewUrl ? "AI Detection Preview" : "Image Preview"}
          </p>
          <div className="overflow-hidden rounded-xl border border-slate-200 shadow-sm">
            <img
              src={annotatedPreviewUrl ?? previewUrl ?? ""}
              alt="Detection preview"
              className="block w-full"
            />
          </div>
          {annotatedPreviewUrl && (
            <p className="mt-1.5 text-xs text-slate-400">
              Colored boxes show detected watermark regions
            </p>
          )}
        </div>

        {/* Right: Candidate list */}
        <div className="space-y-3">
          {/* Bulk actions */}
          {detections.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={selectAll}
                disabled={isRemoving}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 border border-brand-200 hover:bg-brand-100 transition-all disabled:opacity-50"
              >
                <CheckSquare className="h-3.5 w-3.5" />
                Select All
              </button>
              <button
                type="button"
                onClick={deselectAll}
                disabled={isRemoving}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-all disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5" />
                Deselect All
              </button>
            </div>
          )}

          {/* High confidence */}
          {highConf.length > 0 && (
            <DetectionGroup
              title="High Confidence Detections"
              detections={highConf}
              selectedIds={selectedIds}
              onToggle={toggleSelection}
              disabled={isRemoving}
            />
          )}

          {/* Medium confidence */}
          {medConf.length > 0 && (
            <DetectionGroup
              title="Possible Watermarks (Review)"
              detections={medConf}
              selectedIds={selectedIds}
              onToggle={toggleSelection}
              disabled={isRemoving}
            />
          )}

          {/* Low confidence */}
          {lowConf.length > 0 && (
            <DetectionGroup
              title="Low Confidence (Optional)"
              detections={lowConf}
              selectedIds={selectedIds}
              onToggle={toggleSelection}
              disabled={isRemoving}
            />
          )}

          {/* No detections message */}
          {detections.length === 0 && (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
              No watermarks were automatically detected. You can draw boxes manually on the image below.
            </div>
          )}

          {/* Manual selections list */}
          {manualBboxes.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                Manual Selections ({manualBboxes.length})
              </p>
              <div className="space-y-1.5">
                {manualBboxes.map((b) => (
                  <div
                    key={b.id}
                    className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs"
                  >
                    <span className="text-amber-800 font-medium">
                      Manual region: {b.width}×{b.height}px at ({b.x},{b.y})
                    </span>
                    <button
                      type="button"
                      onClick={() => handleRemoveBbox(b.id)}
                      className="ml-2 text-amber-600 hover:text-amber-800"
                      aria-label="Remove manual selection"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              onClick={confirmRemoval}
              disabled={isRemoving || (selectedIds.size === 0)}
              className="inline-flex items-center gap-2 rounded-2xl bg-gradient-to-r from-brand-600 to-brand-500 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-brand-500/25 hover:from-brand-700 hover:to-brand-600 hover:scale-[1.01] transition-all disabled:opacity-50 disabled:scale-100"
            >
              {isRemoving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Wand2 className="h-4 w-4" />
              )}
              {isRemoving
                ? "Removing…"
                : `Remove ${selectedIds.size} Selected`}
            </button>

            <button
              type="button"
              onClick={() => setShowMaskEditor((v) => !v)}
              disabled={isRemoving}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all disabled:opacity-50"
            >
              <Eraser className="h-4 w-4" />
              {showMaskEditor ? "Hide Editor" : "Edit Mask / Add Area"}
            </button>
          </div>

          {errorMessage && stage !== "error" && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-medium text-red-700 flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              {errorMessage}
            </div>
          )}
        </div>
      </div>

      {/* Mask editor */}
      {showMaskEditor && (previewUrl || annotatedPreviewUrl) && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="mb-2 font-semibold text-slate-800 text-sm">
            Mask Editor — drag to add regions
          </p>
          <p className="mb-3 text-xs text-slate-500">
            Drag a box over any area to add it to the removal mask. Blue boxes = AI detections.
            Orange boxes = your manual selections.
          </p>
          <ManualBboxDraw
            imageUrl={previewUrl ?? ""}
            imageW={imageW}
            imageH={imageH}
            onAddBbox={handleAddBbox}
            existingBboxes={manualBboxes}
            aiDetections={detections}
            selectedIds={selectedIds}
            onRemoveId={handleRemoveBbox}
          />
          <p className="mt-2 text-xs text-slate-400">
            {selectedIds.size} region{selectedIds.size === 1 ? "" : "s"} selected for removal
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Detection group component ────────────────────────────────────────────────

interface DetectionGroupProps {
  title: string;
  detections: ImageDetectionResult[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  disabled: boolean;
}

function DetectionGroup({ title, detections, selectedIds, onToggle, disabled }: DetectionGroupProps) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">{title}</p>
      <div className="space-y-2">
        {detections.map((det) => {
          const badge = confidenceBadge(det.confidence);
          const selected = selectedIds.has(det.detection_id);
          return (
            <label
              key={det.detection_id}
              className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                selected
                  ? "border-brand-300 bg-brand-50/60"
                  : "border-slate-200 bg-white hover:border-brand-200"
              } ${disabled ? "pointer-events-none opacity-60" : ""}`}
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggle(det.detection_id)}
                className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                disabled={disabled}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-slate-800 text-sm truncate max-w-[180px]">
                    {typeLabel(det.type)}: {det.label.length > 30 ? det.label.slice(0, 30) + "…" : det.label}
                  </p>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-semibold ${badge.cls}`}>
                    {badge.text}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {det.bbox.width}×{det.bbox.height}px at ({det.bbox.x},{det.bbox.y}) ·{" "}
                  {det.reasons.slice(0, 2).join(", ")}
                </p>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}
