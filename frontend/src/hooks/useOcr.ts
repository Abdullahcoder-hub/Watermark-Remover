import { useCallback, useState } from "react";

import { ApiRequestError, runOcr } from "../services/api";
import type { OcrResponse } from "../types/document";

export type OcrStatus = "idle" | "running" | "success" | "error";

interface UseOcrResult {
  status: OcrStatus;
  result: OcrResponse | null;
  errorMessage: string | null;
  ocr: (documentId: string) => Promise<void>;
  reset: () => void;
}

export function useOcr(): UseOcrResult {
  const [status, setStatus] = useState<OcrStatus>("idle");
  const [result, setResult] = useState<OcrResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const ocr = useCallback(async (documentId: string) => {
    setStatus("running");
    setErrorMessage(null);

    try {
      const response = await runOcr(documentId);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "OCR failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage(null);
  }, []);

  return { status, result, errorMessage, ocr, reset };
}
