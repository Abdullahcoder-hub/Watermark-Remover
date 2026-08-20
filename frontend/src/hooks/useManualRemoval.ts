import { useCallback, useState } from "react";

import { ApiRequestError, manualRemove } from "../services/api";
import type { ManualRegion, ManualRemovalResponse } from "../types/document";

export type ManualRemovalStatus = "idle" | "removing" | "success" | "error";

interface UseManualRemovalResult {
  status: ManualRemovalStatus;
  result: ManualRemovalResponse | null;
  errorMessage: string | null;
  remove: (documentId: string, regions: ManualRegion[], applyToAllPages: boolean) => Promise<void>;
  reset: () => void;
}

export function useManualRemoval(): UseManualRemovalResult {
  const [status, setStatus] = useState<ManualRemovalStatus>("idle");
  const [result, setResult] = useState<ManualRemovalResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const remove = useCallback(async (documentId: string, regions: ManualRegion[], applyToAllPages: boolean) => {
    setStatus("removing");
    setErrorMessage(null);

    try {
      const response = await manualRemove(documentId, regions, applyToAllPages);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Removing the selected area failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage(null);
  }, []);

  return { status, result, errorMessage, remove, reset };
}
