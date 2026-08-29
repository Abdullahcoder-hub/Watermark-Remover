import { AlertTriangle, ChevronLeft, ChevronRight, Eraser, Loader2, Undo2, Wand2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { previewUrl } from "../services/api";
import type { ManualRegion } from "../types/document";

interface ManualSelectionCanvasProps {
  documentId: string;
  pageCount: number;
  scannedPages: Set<number>;
  onSubmit: (regions: ManualRegion[], applyToAllPages: boolean) => void;
  isSubmitting: boolean;
}

interface PixelPoint {
  x: number;
  y: number;
}

// Matches the backend's MAX_INPAINT_AREA_FRACTION safety cap in
// manual_remover.py. Warning here first so the user finds out before
// submitting, not just from the rejection after the fact.
const LARGE_SELECTION_WARNING_THRESHOLD = 0.15;

export function ManualSelectionCanvas({ documentId, pageCount, scannedPages, onSubmit, isSubmitting }: ManualSelectionCanvasProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [regions, setRegions] = useState<ManualRegion[]>([]);
  const [applyToAllPages, setApplyToAllPages] = useState(false);
  const [dragStart, setDragStart] = useState<PixelPoint | null>(null);
  const [dragCurrent, setDragCurrent] = useState<PixelPoint | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  // Bust the browser cache after a removal changes what the page looks like.
  const [previewVersion, setPreviewVersion] = useState(0);
  const imageRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // A tiny watermark logo (the exact case that motivated this fix) is
  // often tucked right in a corner of the page — a completely normal
  // drag toward it easily crosses the image's edge. Tracking on
  // `window` instead of just the container means the drag keeps
  // working even once the cursor leaves the image bounds; the
  // coordinates themselves are still clamped to the image edges below.
  useEffect(() => {
    if (!dragStart) return;

    const toRelativePoint = (clientX: number, clientY: number): PixelPoint | null => {
      const rect = imageRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0 || rect.height === 0) return null;
      const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
      const y = Math.min(Math.max(clientY - rect.top, 0), rect.height);
      return { x: x / rect.width, y: y / rect.height };
    };

    const handleWindowMouseMove = (event: MouseEvent) => {
      const point = toRelativePoint(event.clientX, event.clientY);
      if (point) setDragCurrent(point);
    };

    const handleWindowMouseUp = (event: MouseEvent) => {
      const point = toRelativePoint(event.clientX, event.clientY) ?? dragCurrent;
      if (point && dragStart) {
        const x0 = Math.min(dragStart.x, point.x);
        const y0 = Math.min(dragStart.y, point.y);
        const x1 = Math.max(dragStart.x, point.x);
        const y1 = Math.max(dragStart.y, point.y);
        // Ignore accidental clicks/tiny drags, not legitimately small
        // (but deliberate) selections around a small logo/icon.
        if (x1 - x0 > 0.006 && y1 - y0 > 0.006) {
          setRegions((prev) => [...prev, { page: currentPage, x0, y0, x1, y1 }]);
        }
      }
      setDragStart(null);
      setDragCurrent(null);
    };

    window.addEventListener("mousemove", handleWindowMouseMove);
    window.addEventListener("mouseup", handleWindowMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleWindowMouseMove);
      window.removeEventListener("mouseup", handleWindowMouseUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragStart, currentPage]);

  // Preload the neighboring pages so Next/Prev feels instant once the
  // browser already has the image cached, instead of waiting on a
  // fresh render + network round trip every click.
  useEffect(() => {
    const preload = (page: number) => {
      if (page < 1 || page > pageCount) return;
      const img = new Image();
      img.src = `${previewUrl(documentId, page)}?v=${previewVersion}`;
    };
    preload(currentPage + 1);
    preload(currentPage - 1);
  }, [currentPage, pageCount, documentId, previewVersion]);

  useEffect(() => {
    setImageLoaded(false);
  }, [currentPage, previewVersion]);

  const getRelativePoint = (event: React.MouseEvent<HTMLDivElement>): PixelPoint | null => {
    const rect = imageRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    const x = Math.min(Math.max(event.clientX - rect.left, 0), rect.width);
    const y = Math.min(Math.max(event.clientY - rect.top, 0), rect.height);
    return { x: x / rect.width, y: y / rect.height };
  };

  const handleMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!imageLoaded) return;
    const point = getRelativePoint(event);
    if (point) {
      setDragStart(point);
      setDragCurrent(point);
    }
  };

  const undoLast = () => setRegions((prev) => prev.slice(0, -1));
  const clearAll = () => setRegions([]);

  const goToPage = (page: number) => {
    if (page >= 1 && page <= pageCount) {
      setCurrentPage(page);
    }
  };

  const regionsOnCurrentPage = regions.filter((r) => r.page === currentPage);
  const isCurrentPageScanned = scannedPages.has(currentPage);

  const largeRegionOnScannedPage = isCurrentPageScanned
    ? regionsOnCurrentPage.some((r) => (r.x1 - r.x0) * (r.y1 - r.y0) > LARGE_SELECTION_WARNING_THRESHOLD)
    : false;

  const dragRect =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : null;

  const handleSubmit = () => {
    if (regions.length > 0) {
      onSubmit(regions, applyToAllPages);
      // The submitted regions apply to whatever page state they were
      // drawn against; clear them and bump the preview so the next
      // render reflects the result once it comes back.
      setRegions([]);
      setPreviewVersion((v) => v + 1);
    }
  };

  return (
    <div className="mt-4 rounded-2xl border border-ink/10 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium text-ink">Manually select an area to remove</p>
        {pageCount > 1 && (
          <div className="flex items-center gap-1 text-sm text-ink/60">
            <button
              type="button"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
              className="rounded-lg p-1.5 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[5.5rem] text-center tabular-nums">
              Page {currentPage} of {pageCount}
            </span>
            <button
              type="button"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage >= pageCount}
              className="rounded-lg p-1.5 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <p className="mb-3 text-xs text-ink/50">
        Drag a box over anything to remove — text, images, or logos automatic detection might have missed.
        Works right up to the edge of the page, so corner logos are easy to catch.
      </p>

      <div
        ref={containerRef}
        className="relative inline-block max-w-full cursor-crosshair select-none overflow-hidden rounded-xl border border-ink/10 bg-ink/[0.03]"
        onMouseDown={handleMouseDown}
      >
        {!imageLoaded && (
          <div className="flex h-64 w-full items-center justify-center text-ink/30">
            <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
          </div>
        )}
        <img
          ref={imageRef}
          src={`${previewUrl(documentId, currentPage)}?v=${previewVersion}`}
          alt={`Page ${currentPage} preview`}
          className={`block max-w-full ${imageLoaded ? "" : "hidden"}`}
          draggable={false}
          onLoad={() => setImageLoaded(true)}
        />

        {imageLoaded &&
          regionsOnCurrentPage.map((region, index) => (
            <div
              key={index}
              className="absolute border-2 border-accent bg-accent/20"
              style={{
                left: `${region.x0 * 100}%`,
                top: `${region.y0 * 100}%`,
                width: `${(region.x1 - region.x0) * 100}%`,
                height: `${(region.y1 - region.y0) * 100}%`,
              }}
            />
          ))}

        {dragRect && (
          <div
            className="pointer-events-none absolute border-2 border-dashed border-warn bg-warn/10"
            style={{
              left: `${dragRect.x0 * 100}%`,
              top: `${dragRect.y0 * 100}%`,
              width: `${(dragRect.x1 - dragRect.x0) * 100}%`,
              height: `${(dragRect.y1 - dragRect.y0) * 100}%`,
            }}
          />
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-ink/70">
          <input
            type="checkbox"
            checked={applyToAllPages}
            onChange={(e) => setApplyToAllPages(e.target.checked)}
            className="h-4 w-4 rounded border-ink/30 text-accent focus:ring-accent"
          />
          Apply this selection to all pages
        </label>
      </div>

      {largeRegionOnScannedPage && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-warn/5 p-3 text-sm text-warn">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>
            This is a scanned page and your selection covers a large area. Removing it can't recover
            what was underneath — it will leave a blurred/blank patch instead. Try a tighter box around
            just the watermark for a cleaner result.
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={regions.length === 0 || isSubmitting}
          className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-teal-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-ink/50 disabled:shadow-none"
        >
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Wand2 className="h-4 w-4" aria-hidden="true" />}
          Remove selected area{regions.length === 1 ? "" : "s"} {regions.length > 0 && `(${regions.length})`}
        </button>
        <button
          type="button"
          onClick={undoLast}
          disabled={regions.length === 0}
          className="inline-flex items-center gap-2 rounded-xl border border-ink/10 px-3 py-2 text-sm text-ink/70 hover:bg-ink/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Undo2 className="h-4 w-4" aria-hidden="true" />
          Undo
        </button>
        <button
          type="button"
          onClick={clearAll}
          disabled={regions.length === 0}
          className="inline-flex items-center gap-2 rounded-xl border border-ink/10 px-3 py-2 text-sm text-ink/70 hover:bg-ink/[0.03] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Eraser className="h-4 w-4" aria-hidden="true" />
          Clear
        </button>
      </div>
    </div>
  );
}
