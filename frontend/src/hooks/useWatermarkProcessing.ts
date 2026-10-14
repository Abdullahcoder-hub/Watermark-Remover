import { useCallback, useState } from "react";

import { ApiRequestError, processDocument } from "../services/api";
import type { ProcessResponse } from "../types/document";
import { useJobProgress } from "./useJobProgress";

export type ProcessingStatus = "idle" | "processing" | "success" | "error";

interface UseWatermarkProcessingResult {
  status: ProcessingStatus;
  result: ProcessResponse | null;
  errorMessage: string | null;
  progressMessage: string | null;
  progressPercent: number;
  process: (documentId: string, candidateIds: string[]) => Promise<void>;
  reset: () => void;
}

export function useWatermarkProcessing(): UseWatermarkProcessingResult {
  const [status, setStatus] = useState<ProcessingStatus>("idle");
  const [result, setResult] = useState<ProcessResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { progress, startPolling, reset: resetProgress } = useJobProgress();

  const process = useCallback(async (documentId: string, candidateIds: string[]) => {
    setStatus("processing");
    setErrorMessage(null);
    startPolling(documentId);

    try {
      const response = await processDocument(documentId, candidateIds);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Removing the watermark failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, [startPolling]);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage(null);
    resetProgress();
  }, [resetProgress]);

  return {
    status,
    result,
    errorMessage,
    progressMessage: progress?.message ?? null,
    progressPercent: progress?.percent ?? 0,
    process,
    reset,
  };
}
