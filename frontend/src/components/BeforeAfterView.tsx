import { ChevronLeft, ChevronRight, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import { useState } from "react";

import { previewUrl } from "../services/api";

interface BeforeAfterViewProps {
  documentId: string;
  pageCount: number;
}

const ZOOM_LEVELS = [1, 1.5, 2];

export function BeforeAfterView({ documentId, pageCount }: BeforeAfterViewProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [zoomIndex, setZoomIndex] = useState(0);
  const [retryToken, setRetryToken] = useState(0);
  const [imageStates, setImageStates] = useState<Record<string, "loaded" | "error">>({});

  const goToPage = (page: number) => {
    if (page >= 1 && page <= pageCount) setCurrentPage(page);
  };

  const zoom = ZOOM_LEVELS[zoomIndex];

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
            {(() => {
              const imageKey = `${documentId}-${currentPage}-${version}-${retryToken}`;
              const imageState = imageStates[imageKey];
              return (
                <div className="relative min-h-64 overflow-auto rounded-xl border border-ink/10 bg-ink/[0.03]" style={{ maxHeight: "70vh" }}>
                  {imageState !== "loaded" && (
                    <div className="absolute inset-0 z-10 flex min-h-64 items-center justify-center bg-white/80 text-ink/40">
                      {imageState === "error" ? (
                        <div className="flex flex-col items-center gap-2 p-4 text-center text-sm">
                          <span>Could not load this slide preview.</span>
                          <button
                            type="button"
                            className="rounded-lg border border-ink/10 px-3 py-1.5 font-medium text-ink hover:bg-ink/5"
                            onClick={() => setRetryToken((token) => token + 1)}
                          >
                            Try again
                          </button>
                        </div>
                      ) : (
                        <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
                      )}
                    </div>
                  )}
                  <img
                    key={imageKey}
                    src={previewUrl(documentId, currentPage, version, retryToken || undefined)}
                    alt={`Page ${currentPage}, ${version === "original" ? "before" : "after"} cleanup`}
                    className={`block ${imageState === "error" ? "invisible" : ""}`}
                    style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
                    onLoad={() =>
                      setImageStates((states) => ({ ...states, [imageKey]: "loaded" }))
                    }
                    onError={() =>
                      setImageStates((states) => ({ ...states, [imageKey]: "error" }))
                    }
                  />
                </div>
              );
            })()}
          </div>
        ))}
      </div>
    </div>
  );
}
