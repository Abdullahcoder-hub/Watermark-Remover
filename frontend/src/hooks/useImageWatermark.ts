import { useCallback, useRef, useState } from "react";

import {
  ApiRequestError,
  detectImageWatermark,
  previewImageDetections,
  removeImageWatermark,
} from "../services/api";
import type { ImageDetectionResponse, ImageDetectionResult } from "../types/document";

// ─── State types ─────────────────────────────────────────────────────────────

export type ImageWorkflowStage =
  | "idle"
  | "uploading"
  | "detecting"
  | "detected"
  | "removing"
  | "done"
  | "error";

interface ImageWatermarkState {
  stage: ImageWorkflowStage;
  file: File | null;
  previewUrl: string | null;          // original image object URL (for display)
  annotatedPreviewUrl: string | null; // preview with detection overlays
  resultUrl: string | null;           // cleaned image download URL
  resultBlob: Blob | null;
  detection: ImageDetectionResponse | null;
  selectedIds: Set<string>;
  errorMessage: string | null;
  uploadProgress: number;
}

interface UseImageWatermarkReturn extends ImageWatermarkState {
  startWithFile: (file: File) => Promise<void>;
  toggleSelection: (id: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  addManualBbox: (bbox: { x: number; y: number; width: number; height: number }) => void;
  removeById: (id: string) => void;
  confirmRemoval: () => Promise<void>;
  scanAgain: () => Promise<void>;
  reset: () => void;
}

export function useImageWatermark(): UseImageWatermarkReturn {
  const [state, setState] = useState<ImageWatermarkState>({
    stage: "idle",
    file: null,
    previewUrl: null,
    annotatedPreviewUrl: null,
    resultUrl: null,
    resultBlob: null,
    detection: null,
    selectedIds: new Set(),
    errorMessage: null,
    uploadProgress: 0,
  });

  // Track extra manual bboxes added by the user (not from AI detection)
  const manualBboxesRef = useRef<Array<{ id: string; x: number; y: number; width: number; height: number }>>([]);

  const setStage = (stage: ImageWorkflowStage, extra?: Partial<ImageWatermarkState>) =>
    setState((prev) => ({ ...prev, stage, ...extra }));

  // ─── Revoke old object URLs to avoid memory leaks ───────────────────────
  const revokeUrls = (s: ImageWatermarkState) => {
    if (s.previewUrl) URL.revokeObjectURL(s.previewUrl);
    if (s.annotatedPreviewUrl) URL.revokeObjectURL(s.annotatedPreviewUrl);
    if (s.resultUrl) URL.revokeObjectURL(s.resultUrl);
  };

  // ─── Main flow entry point ───────────────────────────────────────────────
  const startWithFile = useCallback(async (file: File) => {
    // Create a local preview URL
    const localPreview = URL.createObjectURL(file);

    setState((prev) => {
      revokeUrls(prev);
      return {
        stage: "detecting",
        file,
        previewUrl: localPreview,
        annotatedPreviewUrl: null,
        resultUrl: null,
        resultBlob: null,
        detection: null,
        selectedIds: new Set(),
        errorMessage: null,
        uploadProgress: 0,
      };
    });

    manualBboxesRef.current = [];

    try {
      const detection = await detectImageWatermark(file, (pct) =>
        setState((prev) => ({ ...prev, uploadProgress: pct })),
      );

      // Pre-select high-confidence detections (>= 0.70)
      const autoSelected = new Set(
        detection.detections
          .filter((d) => d.confidence >= 0.70)
          .map((d) => d.detection_id),
      );

      // Build annotated preview
      let annotatedUrl: string | null = null;
      try {
        annotatedUrl = await previewImageDetections(file, detection.detections as object[]);
      } catch {
        // non-critical: fall back to plain preview
      }

      setState((prev) => ({
        ...prev,
        stage: "detected",
        detection,
        selectedIds: autoSelected,
        annotatedPreviewUrl: annotatedUrl,
        errorMessage: null,
      }));
    } catch (err) {
      const msg =
        err instanceof ApiRequestError
          ? err.message
          : "Watermark detection failed. Please try again.";
      setStage("error", { errorMessage: msg });
    }
  }, []);

  // ─── Selection management ─────────────────────────────────────────────────
  const toggleSelection = useCallback((id: string) => {
    setState((prev) => {
      const next = new Set(prev.selectedIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { ...prev, selectedIds: next };
    });
  }, []);

  const selectAll = useCallback(() => {
    setState((prev) => {
      const allIds = new Set([
        ...(prev.detection?.detections.map((d) => d.detection_id) ?? []),
        ...manualBboxesRef.current.map((b) => b.id),
      ]);
      return { ...prev, selectedIds: allIds };
    });
  }, []);

  const deselectAll = useCallback(() => {
    setState((prev) => ({ ...prev, selectedIds: new Set() }));
  }, []);

  const addManualBbox = useCallback(
    (bbox: { x: number; y: number; width: number; height: number }) => {
      const id = `manual_${Date.now()}_${Math.random().toString(36).slice(2)}`;
      manualBboxesRef.current = [...manualBboxesRef.current, { id, ...bbox }];
      setState((prev) => {
        const next = new Set(prev.selectedIds);
        next.add(id);
        return { ...prev, selectedIds: next };
      });
    },
    [],
  );

  const removeById = useCallback((id: string) => {
    manualBboxesRef.current = manualBboxesRef.current.filter((b) => b.id !== id);
    setState((prev) => {
      const next = new Set(prev.selectedIds);
      next.delete(id);
      return { ...prev, selectedIds: next };
    });
  }, []);

  // ─── Removal ──────────────────────────────────────────────────────────────
  const confirmRemoval = useCallback(async () => {
    setState((prev) => {
      if (!prev.file || (prev.selectedIds.size === 0 && manualBboxesRef.current.length === 0))
        return prev;
      return { ...prev, stage: "removing", errorMessage: null };
    });

    setState((prev) => {
      if (!prev.file) return prev;

      const file = prev.file;
      const detection = prev.detection;
      const selectedIds = prev.selectedIds;

      // Collect bboxes from selected AI detections
      const aiBboxes: Array<{ x: number; y: number; width: number; height: number }> =
        (detection?.detections ?? [])
          .filter((d) => selectedIds.has(d.detection_id))
          .map((d) => ({
            x: d.bbox.x,
            y: d.bbox.y,
            width: d.bbox.width,
            height: d.bbox.height,
          }));

      // Collect bboxes from manual selections
      const manualBboxes = manualBboxesRef.current
        .filter((b) => selectedIds.has(b.id))
        .map(({ id: _id, ...bbox }) => bbox);

      const allBboxes = [...aiBboxes, ...manualBboxes];

      if (allBboxes.length === 0) {
        return { ...prev, stage: "detected", errorMessage: "No regions selected for removal." };
      }

      // Kick off async removal
      (async () => {
        try {
          const blob = await removeImageWatermark(file, allBboxes);
          const resultUrl = URL.createObjectURL(blob);
          setState((s) => ({
            ...s,
            stage: "done",
            resultBlob: blob,
            resultUrl,
          }));
        } catch (err) {
          const msg =
            err instanceof ApiRequestError
              ? err.message
              : "Watermark removal failed. Please try again.";
          setState((s) => ({ ...s, stage: "error", errorMessage: msg }));
        }
      })();

      return prev; // Return immediately; state will update async
    });
  }, []);

  // ─── Re-scan ──────────────────────────────────────────────────────────────
  const scanAgain = useCallback(async () => {
    setState((prev) => {
      if (!prev.file) return prev;
      return { ...prev, stage: "detecting", errorMessage: null };
    });

    setState((prev) => {
      const file = prev.file;
      if (!file) return prev;
      (async () => {
        await startWithFile(file);
      })();
      return prev;
    });
  }, [startWithFile]);

  // ─── Reset ───────────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    setState((prev) => {
      revokeUrls(prev);
      return {
        stage: "idle",
        file: null,
        previewUrl: null,
        annotatedPreviewUrl: null,
        resultUrl: null,
        resultBlob: null,
        detection: null,
        selectedIds: new Set(),
        errorMessage: null,
        uploadProgress: 0,
      };
    });
    manualBboxesRef.current = [];
  }, []);

  return {
    ...state,
    startWithFile,
    toggleSelection,
    selectAll,
    deselectAll,
    addManualBbox,
    removeById,
    confirmRemoval,
    scanAgain,
    reset,
  };
}
