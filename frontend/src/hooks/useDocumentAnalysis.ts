import { useCallback, useState } from "react";

import { analyzeDocument, ApiRequestError } from "../services/api";
import type { DocumentAnalysisResponse } from "../types/document";

export type AnalysisStatus = "idle" | "analyzing" | "success" | "error";

interface UseDocumentAnalysisResult {
  status: AnalysisStatus;
  result: DocumentAnalysisResponse | null;
  errorMessage: string | null;
  analyze: (documentId: string) => Promise<void>;
  reset: () => void;
}

export function useDocumentAnalysis(): UseDocumentAnalysisResult {
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [result, setResult] = useState<DocumentAnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const analyze = useCallback(async (documentId: string) => {
    setStatus("analyzing");
    setErrorMessage(null);

    try {
      const response = await analyzeDocument(documentId);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Analysis failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage(null);
  }, []);

  return { status, result, errorMessage, analyze, reset };
}
