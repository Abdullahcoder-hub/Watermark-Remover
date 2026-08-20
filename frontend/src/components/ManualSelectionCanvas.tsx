import { ChevronLeft, ChevronRight, Eraser, Undo2, Wand2 } from "lucide-react";
import { useRef, useState } from "react";

import { previewUrl } from "../services/api";
import type { ManualRegion } from "../types/document";

interface ManualSelectionCanvasProps {
  documentId: string;
  pageCount: number;
  onSubmit: (regions: ManualRegion[], applyToAllPages: boolean) => void;
  isSubmitting: boolean;
}

interface PixelPoint {
  x: number;
  y: number;
}

export function ManualSelectionCanvas({ documentId, pageCount, onSubmit, isSubmitting }: ManualSelectionCanvasProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [regions, setRegions] = useState<ManualRegion[]>([]);
  const [applyToAllPages, setApplyToAllPages] = useState(false);
  const [dragStart, setDragStart] = useState<PixelPoint | null>(null);
  const [dragCurrent, setDragCurrent] = useState<PixelPoint | null>(null);
  // Bust the browser cache after a removal changes what the page looks like.
  const [previewVersion, setPreviewVersion] = useState(0);
  const imageRef = useRef<HTMLImageElement>(null);

  const getRelativePoint = (event: React.MouseEvent<HTMLDivElement>): PixelPoint | null => {
    const rect = imageRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = Math.min(Math.max(event.clientX - rect.left, 0), rect.width);
    const y = Math.min(Math.max(event.clientY - rect.top, 0), rect.height);
    return { x: x / rect.width, y: y / rect.height }; // already fractional
  };

  const handleMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
    const point = getRelativePoint(event);
    if (point) {
      setDragStart(point);
      setDragCurrent(point);
    }
  };

  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!dragStart) return;
    const point = getRelativePoint(event);
    if (point) setDragCurrent(point);
  };

  const handleMouseUp = () => {
    if (dragStart && dragCurrent) {
      const x0 = Math.min(dragStart.x, dragCurrent.x);
      const y0 = Math.min(dragStart.y, dragCurrent.y);
      const x1 = Math.max(dragStart.x, dragCurrent.x);
      const y1 = Math.max(dragStart.y, dragCurrent.y);
      // Ignore accidental clicks/tiny drags.
      if (x1 - x0 > 0.01 && y1 - y0 > 0.01) {
        setRegions((prev) => [...prev, { page: currentPage, x0, y0, x1, y1 }]);
      }
    }
    setDragStart(null);
    setDragCurrent(null);
  };

  const undoLast = () => setRegions((prev) => prev.slice(0, -1));
  const clearAll = () => setRegions([]);

  const regionsOnCurrentPage = regions.filter((r) => r.page === currentPage);

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
    <div className="mt-4 rounded-xl border border-ink/10 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium text-ink">Manually select an area to remove</p>
        {pageCount > 1 && (
          <div className="flex items-center gap-2 text-sm text-ink/60">
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
              className="rounded p-1 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span>
              Page {currentPage} of {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
              disabled={currentPage >= pageCount}
              className="rounded p-1 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Next page"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>

      <p className="mb-3 text-xs text-ink/50">
        Drag a box over anything to remove — text, images, or logos automatic detection might have missed.
      </p>

      <div
        className="relative inline-block max-w-full cursor-crosshair select-none overflow-hidden rounded-lg border border-ink/10"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => {
          setDragStart(null);
          setDragCurrent(null);
        }}
      >
        <img
          ref={imageRef}
          src={`${previewUrl(documentId, currentPage)}?v=${previewVersion}`}
          alt={`Page ${currentPage} preview`}
          className="block max-w-full"
          draggable={false}
        />

        {regionsOnCurrentPage.map((region, index) => (
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

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={regions.length === 0 || isSubmitting}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Wand2 className="h-4 w-4" aria-hidden="true" />
          Remove selected area{regions.length === 1 ? "" : "s"} {regions.length > 0 && `(${regions.length})`}
        </button>
        <button
          type="button"
          onClick={undoLast}
          disabled={regions.length === 0}
          className="inline-flex items-center gap-2 rounded-lg border border-ink/15 px-3 py-2 text-sm text-ink hover:bg-ink/5 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Undo2 className="h-4 w-4" aria-hidden="true" />
          Undo
        </button>
        <button
          type="button"
          onClick={clearAll}
          disabled={regions.length === 0}
          className="inline-flex items-center gap-2 rounded-lg border border-ink/15 px-3 py-2 text-sm text-ink hover:bg-ink/5 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Eraser className="h-4 w-4" aria-hidden="true" />
          Clear
        </button>
      </div>
    </div>
  );
}
