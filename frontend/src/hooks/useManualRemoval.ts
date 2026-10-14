import { useCallback, useState } from "react";

import { ApiRequestError, manualRemove } from "../services/api";
import type { ManualRegion, ManualRemovalResponse } from "../types/document";
import { useJobProgress } from "./useJobProgress";

export type ManualRemovalStatus = "idle" | "removing" | "success" | "error";

interface UseManualRemovalResult {
  status: ManualRemovalStatus;
  result: ManualRemovalResponse | null;
  errorMessage: string | null;
  progressMessage: string | null;
  progressPercent: number;
  remove: (documentId: string, regions: ManualRegion[], applyToAllPages: boolean) => Promise<void>;
  reset: () => void;
}

export function useManualRemoval(): UseManualRemovalResult {
  const [status, setStatus] = useState<ManualRemovalStatus>("idle");
  const [result, setResult] = useState<ManualRemovalResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { progress, startPolling, reset: resetProgress } = useJobProgress();

  const remove = useCallback(async (documentId: string, regions: ManualRegion[], applyToAllPages: boolean) => {
    setStatus("removing");
    setErrorMessage(null);
    startPolling(documentId);

    try {
      const response = await manualRemove(documentId, regions, applyToAllPages);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Removing the selected area failed. Please try again.";
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
    remove,
    reset,
  };
}
