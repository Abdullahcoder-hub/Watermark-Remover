import { ChevronLeft, ChevronRight, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useState } from "react";

import { previewUrl } from "../services/api";

interface BeforeAfterViewProps {
  documentId: string;
  pageCount: number;
}

const ZOOM_LEVELS = [1, 1.5, 2];

export function BeforeAfterView({ documentId, pageCount }: BeforeAfterViewProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [zoomIndex, setZoomIndex] = useState(0);
  const [loadedCount, setLoadedCount] = useState(0);
  // Bumped whenever the page changes, so the loading state resets and
  // we don't briefly show the previous page's images mid-swap.
  const [renderKey, setRenderKey] = useState(0);

  useEffect(() => {
    setLoadedCount(0);
    setRenderKey((k) => k + 1);
  }, [currentPage]);

  const goToPage = (page: number) => {
    if (page >= 1 && page <= pageCount) setCurrentPage(page);
  };

  const zoom = ZOOM_LEVELS[zoomIndex];
  const bothLoaded = loadedCount >= 2;

  return (
    <div className="mt-4 rounded-2xl border border-ink/10 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-ink">Before &amp; after</p>
        <div className="flex items-center gap-3">
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
          <div className="flex items-center gap-1 border-l border-ink/10 pl-3 text-ink/60">
            <button
              type="button"
              onClick={() => setZoomIndex((z) => Math.max(0, z - 1))}
              disabled={zoomIndex === 0}
              className="rounded-lg p-1.5 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Zoom out"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <span className="min-w-[3rem] text-center text-sm tabular-nums">{Math.round(zoom * 100)}%</span>
            <button
              type="button"
              onClick={() => setZoomIndex((z) => Math.min(ZOOM_LEVELS.length - 1, z + 1))}
              disabled={zoomIndex === ZOOM_LEVELS.length - 1}
              className="rounded-lg p-1.5 hover:bg-ink/5 disabled:opacity-30"
              aria-label="Zoom in"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {(["original", "current"] as const).map((version) => (
          <div key={version}>
            <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink/40">
              {version === "original" ? "Before" : "After"}
            </p>
            <div className="relative overflow-auto rounded-xl border border-ink/10 bg-ink/[0.03]" style={{ maxHeight: "70vh" }}>
              {!bothLoaded && (
                <div className="flex h-64 w-full items-center justify-center text-ink/30">
                  <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
                </div>
              )}
              <img
                key={`${version}-${renderKey}`}
                src={previewUrl(documentId, currentPage, version)}
                alt={`Page ${currentPage}, ${version === "original" ? "before" : "after"} cleanup`}
                className={bothLoaded ? "block" : "hidden"}
                style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
                onLoad={() => setLoadedCount((c) => c + 1)}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
