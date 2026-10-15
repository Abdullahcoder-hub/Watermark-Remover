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
  /** How often to poll in milliseconds (default: 500ms) */
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
  const { intervalMs = 500 } = options;
  const [progress, setProgress] = useState<JobProgressResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const documentIdRef = useRef<string | null>(null);
  const pollingRef = useRef(false);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const poll = useCallback(async () => {
    const docId = documentIdRef.current;
    if (!docId || !pollingRef.current) return;

    try {
      const result = await getJobProgress(docId);
      if (!pollingRef.current || documentIdRef.current !== docId) return;
      setProgress(result);
      if (TERMINAL_STAGES.includes(result.stage)) {
        stopPolling();
        return;
      }
    } catch {
      // Silently ignore polling errors — the main request handler shows errors
    }

    if (pollingRef.current && documentIdRef.current === docId) {
      timeoutRef.current = setTimeout(() => void poll(), intervalMs);
    }
  }, [intervalMs, stopPolling]);

  const startPolling = useCallback(
    (documentId: string) => {
      // Stop any existing poll cycle
      stopPolling();

      documentIdRef.current = documentId;
      pollingRef.current = true;
      setIsPolling(true);

      // Immediate first fetch
      void poll();
    },
    [poll, stopPolling],
  );

  const reset = useCallback(() => {
    stopPolling();
    documentIdRef.current = null;
    setProgress(null);
  }, [stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      pollingRef.current = false;
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return { progress, isPolling, startPolling, stopPolling, reset };
}
