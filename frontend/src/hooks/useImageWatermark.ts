import { useCallback, useRef, useState } from "react";

import {
  ApiRequestError,
  detectImageWatermark,
  previewImageDetections,
  removeImageWatermark,
} from "../services/api";
import type { ImageDetectionResponse } from "../types/document";

// ─── State types ─────────────────────────────────────────────────────────────

export type ImageWorkflowStage =
  | "idle"
  | "detecting"
  | "detected"
  | "removing"
  | "done"
  | "error";

interface ImageWatermarkState {
  stage: ImageWorkflowStage;
  file: File | null;
  previewUrl: string | null;
  annotatedPreviewUrl: string | null;
  resultUrl: string | null;
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
  /** Adds a manual bbox, returns the generated id for tracking */
  addManualBbox: (bbox: { x: number; y: number; width: number; height: number }) => string;
  removeById: (id: string) => void;
  confirmRemoval: () => Promise<void>;
  scanAgain: () => Promise<void>;
  reset: () => void;
}

// Extra manual bboxes the user draws on the canvas (not from AI)
interface ManualBbox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

const INITIAL_STATE: ImageWatermarkState = {
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

export function useImageWatermark(): UseImageWatermarkReturn {
  const [state, setState] = useState<ImageWatermarkState>(INITIAL_STATE);
  const manualBboxesRef = useRef<ManualBbox[]>([]);
  // Keep a ref to the current file so callbacks can read it without stale closure
  const fileRef = useRef<File | null>(null);

  // Revoke blob URLs to prevent memory leaks
  const revokeAll = (s: ImageWatermarkState) => {
    if (s.previewUrl?.startsWith("blob:")) URL.revokeObjectURL(s.previewUrl);
    if (s.annotatedPreviewUrl?.startsWith("blob:")) URL.revokeObjectURL(s.annotatedPreviewUrl);
    if (s.resultUrl?.startsWith("blob:")) URL.revokeObjectURL(s.resultUrl);
  };

  // ─── Core: run detection for a given file ────────────────────────────────
  const startWithFile = useCallback(async (file: File) => {
    setState((prev) => {
      revokeAll(prev);
      return {
        ...INITIAL_STATE,
        stage: "detecting",
        file,
        previewUrl: URL.createObjectURL(file),
      };
    });
    fileRef.current = file;
    manualBboxesRef.current = [];

    try {
      const detection = await detectImageWatermark(file, (pct) =>
        setState((prev) => ({ ...prev, uploadProgress: pct })),
      );

      // Pre-select high-confidence detections (≥ 0.70)
      const autoSelected = new Set(
        detection.detections
          .filter((d) => d.confidence >= 0.70)
          .map((d) => d.detection_id),
      );

      // Generate annotated preview (non-critical — failures are silent)
      let annotatedPreviewUrl: string | null = null;
      try {
        annotatedPreviewUrl = await previewImageDetections(file, detection.detections as object[]);
      } catch {
        // fall back to plain preview
      }

      setState((prev) => ({
        ...prev,
        stage: "detected",
        detection,
        selectedIds: autoSelected,
        annotatedPreviewUrl,
        errorMessage: null,
      }));
    } catch (err) {
      const msg =
        err instanceof ApiRequestError
          ? err.message
          : "Watermark detection failed. Please try again.";
      setState((prev) => ({ ...prev, stage: "error", errorMessage: msg }));
    }
  }, []);

  // ─── Selection helpers ────────────────────────────────────────────────────
  const toggleSelection = useCallback((id: string) => {
    setState((prev) => {
      const next = new Set(prev.selectedIds);
      if (next.has(id)) next.delete(id); else next.add(id);
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
    (bbox: { x: number; y: number; width: number; height: number }): string => {
      const id = `manual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      manualBboxesRef.current = [...manualBboxesRef.current, { id, ...bbox }];
      setState((prev) => {
        const next = new Set(prev.selectedIds);
        next.add(id);
        return { ...prev, selectedIds: next };
      });
      return id;
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
    // Read current state synchronously to avoid stale closures
    let currentFile: File | null = null;
    let currentDetection: ImageDetectionResponse | null = null;
    let currentSelectedIds: Set<string> = new Set();

    setState((prev) => {
      currentFile = prev.file;
      currentDetection = prev.detection;
      currentSelectedIds = prev.selectedIds;
      if (!currentFile || currentSelectedIds.size === 0) return prev;
      return { ...prev, stage: "removing", errorMessage: null };
    });

    if (!currentFile || currentSelectedIds.size === 0) return;

    // Collect AI detection bboxes
    const aiBboxes = (currentDetection?.detections ?? [])
      .filter((d) => currentSelectedIds.has(d.detection_id))
      .map((d) => ({ x: d.bbox.x, y: d.bbox.y, width: d.bbox.width, height: d.bbox.height }));

    // Collect manual bboxes
    const manualBboxes = manualBboxesRef.current
      .filter((b) => currentSelectedIds.has(b.id))
      .map(({ id: _id, ...rest }) => rest);

    const allBboxes = [...aiBboxes, ...manualBboxes];

    if (allBboxes.length === 0) {
      setState((prev) => ({ ...prev, stage: "detected", errorMessage: "No regions selected for removal." }));
      return;
    }

    try {
      const blob = await removeImageWatermark(currentFile, allBboxes);
      const resultUrl = URL.createObjectURL(blob);
      setState((prev) => ({
        ...prev,
        stage: "done",
        resultBlob: blob,
        resultUrl,
      }));
    } catch (err) {
      const msg =
        err instanceof ApiRequestError
          ? err.message
          : "Watermark removal failed. Please try again.";
      setState((prev) => ({ ...prev, stage: "error", errorMessage: msg }));
    }
  }, []);

  // ─── Re-scan ──────────────────────────────────────────────────────────────
  const scanAgain = useCallback(async () => {
    const file = fileRef.current;
    if (file) {
      await startWithFile(file);
    }
  }, [startWithFile]);

  // ─── Reset ────────────────────────────────────────────────────────────────
  const reset = useCallback(() => {
    setState((prev) => {
      revokeAll(prev);
      return { ...INITIAL_STATE };
    });
    manualBboxesRef.current = [];
    fileRef.current = null;
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
