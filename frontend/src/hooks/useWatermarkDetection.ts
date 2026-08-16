import { useCallback, useState } from "react";

import { ApiRequestError, detectWatermarks } from "../services/api";
import type { DetectionResponse } from "../types/document";

export type DetectionStatus = "idle" | "detecting" | "success" | "error";

interface UseWatermarkDetectionResult {
  status: DetectionStatus;
  result: DetectionResponse | null;
  errorMessage: string | null;
  detect: (documentId: string) => Promise<void>;
  reset: () => void;
}

export function useWatermarkDetection(): UseWatermarkDetectionResult {
  const [status, setStatus] = useState<DetectionStatus>("idle");
  const [result, setResult] = useState<DetectionResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const detect = useCallback(async (documentId: string) => {
    setStatus("detecting");
    setErrorMessage(null);

    try {
      const response = await detectWatermarks(documentId);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Watermark detection failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage(null);
  }, []);

  return { status, result, errorMessage, detect, reset };
}
