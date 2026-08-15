import { useCallback, useState } from "react";

import { ApiRequestError, uploadDocument } from "../services/api";
import type { DocumentUploadResponse } from "../types/document";

export type UploadStatus = "idle" | "uploading" | "success" | "error";

interface UseDocumentUploadResult {
  status: UploadStatus;
  progress: number;
  result: DocumentUploadResponse | null;
  errorMessage: string | null;
  upload: (file: File) => Promise<void>;
  reset: () => void;
}

export function useDocumentUpload(): UseDocumentUploadResult {
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<DocumentUploadResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const upload = useCallback(async (file: File) => {
    setStatus("uploading");
    setProgress(0);
    setErrorMessage(null);

    try {
      const response = await uploadDocument(file, setProgress);
      setResult(response);
      setStatus("success");
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : "Upload failed. Please try again.";
      setErrorMessage(message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setStatus("idle");
    setProgress(0);
    setResult(null);
    setErrorMessage(null);
  }, []);

  return { status, progress, result, errorMessage, upload, reset };
}
