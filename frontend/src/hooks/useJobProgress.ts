/**
 * useJobProgress — polls GET /api/v1/documents/{documentId}/progress
 * every `intervalMs` milliseconds while the job is active.
 *
 * Automatically stops polling when stage reaches a terminal state
 * ("processed", "analyzed", "detected", "error") or when documentId is null.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { getJobProgress } from "../services/api";
import type { JobProgressResponse } from "../types/document";

const TERMINAL_STAGES: JobProgressResponse["stage"][] = [
  "processed",
  "analyzed",
  "detected",
  "error",
];

interface UseJobProgressOptions {
  /** How often to poll in milliseconds (default: 1200ms) */
  intervalMs?: number;
}

interface UseJobProgressResult {
  progress: JobProgressResponse | null;
  isPolling: boolean;
  startPolling: (documentId: string) => void;
  stopPolling: () => void;
  reset: () => void;
}

export function useJobProgress(options: UseJobProgressOptions = {}): UseJobProgressResult {
  const { intervalMs = 1200 } = options;
  const [progress, setProgress] = useState<JobProgressResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const documentIdRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const poll = useCallback(async () => {
    const docId = documentIdRef.current;
    if (!docId) return;

    try {
      const result = await getJobProgress(docId);
      setProgress(result);
      if (TERMINAL_STAGES.includes(result.stage)) {
        stopPolling();
      }
    } catch {
      // Silently ignore polling errors — the main request handler shows errors
    }
  }, [stopPolling]);

  const startPolling = useCallback(
    (documentId: string) => {
      // Stop any existing poll cycle
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }

      documentIdRef.current = documentId;
      setIsPolling(true);

      // Immediate first fetch
      void poll();

      intervalRef.current = setInterval(() => {
        void poll();
      }, intervalMs);
    },
    [poll, intervalMs],
  );

  const reset = useCallback(() => {
    stopPolling();
    documentIdRef.current = null;
    setProgress(null);
  }, [stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return { progress, isPolling, startPolling, stopPolling, reset };
}
