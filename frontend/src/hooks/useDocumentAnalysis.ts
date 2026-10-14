import { useCallback, useState } from "react";

import { analyzeDocument, ApiRequestError } from "../services/api";
import type { DocumentAnalysisResponse } from "../types/document";
import { useJobProgress } from "./useJobProgress";

export type AnalysisStatus = "idle" | "analyzing" | "success" | "error";

interface UseDocumentAnalysisResult {
  status: AnalysisStatus;
  result: DocumentAnalysisResponse | null;
  errorMessage: string | null;
  progressMessage: string | null;
  progressPercent: number;
  analyze: (documentId: string) => Promise<void>;
  reset: () => void;
}

export function useDocumentAnalysis(): UseDocumentAnalysisResult {
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [result, setResult] = useState<DocumentAnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const { progress, startPolling, reset: resetProgress } = useJobProgress();

  const analyze = useCallback(async (documentId: string) => {
    setStatus("analyzing");
    setErrorMessage(null);
    startPolling(documentId);

    try {
      const response = await analyzeDocument(documentId);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Analysis failed. Please try again.";
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
    analyze,
    reset,
  };
}
