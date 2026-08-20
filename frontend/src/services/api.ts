import axios, { AxiosError } from "axios";

import type {
  ApiErrorResponse,
  DetectionResponse,
  DocumentAnalysisResponse,
  DocumentUploadResponse,
  ManualRegion,
  ManualRemovalResponse,
  ProcessResponse,
} from "../types/document";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

export class ApiRequestError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    this.name = "ApiRequestError";
  }
}

function toApiRequestError(error: unknown): ApiRequestError {
  const axiosError = error as AxiosError<ApiErrorResponse>;
  const detail = axiosError.response?.data;

  if (detail && "error" in detail) {
    return new ApiRequestError(detail.error.code, detail.error.message);
  }

  return new ApiRequestError("NETWORK_ERROR", "Could not reach the server. Please check your connection and try again.");
}

export async function uploadDocument(file: File, onProgress?: (percent: number) => void): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await apiClient.post<DocumentUploadResponse>("/api/v1/documents/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    });
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await apiClient.get("/api/v1/health");
    return response.data.status === "ok";
  } catch {
    return false;
  }
}

export async function analyzeDocument(documentId: string): Promise<DocumentAnalysisResponse> {
  try {
    const response = await apiClient.post<DocumentAnalysisResponse>(`/api/v1/documents/${documentId}/analyze`);
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export async function detectWatermarks(documentId: string): Promise<DetectionResponse> {
  try {
    const response = await apiClient.post<DetectionResponse>(`/api/v1/documents/${documentId}/detect`);
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export async function processDocument(documentId: string, candidateIds: string[]): Promise<ProcessResponse> {
  try {
    const response = await apiClient.post<ProcessResponse>(`/api/v1/documents/${documentId}/process`, {
      candidate_ids: candidateIds,
      pages: "all",
    });
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export function downloadUrl(documentId: string): string {
  return `${API_BASE_URL}/api/v1/documents/${documentId}/download`;
}

export function previewUrl(documentId: string, page: number): string {
  return `${API_BASE_URL}/api/v1/documents/${documentId}/preview/${page}`;
}

export async function manualRemove(
  documentId: string,
  regions: ManualRegion[],
  applyToAllPages: boolean,
): Promise<ManualRemovalResponse> {
  try {
    const response = await apiClient.post<ManualRemovalResponse>(`/api/v1/documents/${documentId}/manual-remove`, {
      regions,
      apply_to_all_pages: applyToAllPages,
    });
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}
