import axios, { AxiosError } from "axios";

import type {
  ApiErrorResponse,
  DetectionResponse,
  DocumentAnalysisResponse,
  DocumentUploadResponse,
  ImageDetectionResponse,
  ManualRegion,
  ManualRemovalResponse,
  OcrResponse,
  ProcessResponse,
} from "../types/document";

const getApiBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === "string" && envUrl.trim() !== "") {
    return envUrl.trim().replace(/\/+$/, "");
  }
  return import.meta.env.DEV ? "http://localhost:8000" : "";
};

export const API_BASE_URL = getApiBaseUrl();

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

  // A timeout is not the same problem as "server unreachable" — OCR in
  // particular can genuinely take a minute or more on a multi-page
  // scanned document, and telling the user to "check your connection"
  // when the real cause is just a slow operation is actively
  // misleading (it reads as a network failure when nothing is wrong).
  if (axiosError.code === "ECONNABORTED" || axiosError.message?.toLowerCase().includes("timeout")) {
    return new ApiRequestError(
      "TIMEOUT",
      "This is taking longer than expected. Large or scanned documents can take a minute or more — please wait a moment and try again rather than clicking repeatedly.",
    );
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

export function previewUrl(
  documentId: string,
  page: number,
  version: "current" | "original" = "current",
  cacheBust?: number,
): string {
  const base = `${API_BASE_URL}/api/v1/documents/${documentId}/preview/${page}?version=${version}`;
  return cacheBust === undefined ? base : `${base}&v=${cacheBust}`;
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

export async function runOcr(documentId: string): Promise<OcrResponse> {
  try {
    // OCR can genuinely take a while — measured ~35s for an 8-page
    // scanned document; a longer one could take several minutes.
    // Generous timeout so a slow-but-working request doesn't get
    // mistaken for a connection failure.
    const response = await apiClient.post<OcrResponse>(
      `/api/v1/documents/${documentId}/ocr`,
      {},
      { timeout: 300_000 },
    );
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

// ─── Image Watermark Detection / Removal ─────────────────────────────────────

export async function detectImageWatermark(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<ImageDetectionResponse> {
  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await apiClient.post<ImageDetectionResponse>(
      "/api/v1/images/detect-watermark",
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (event) => {
          if (onProgress && event.total) {
            onProgress(Math.round((event.loaded / event.total) * 100));
          }
        },
      },
    );
    return response.data;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export async function removeImageWatermark(
  file: File,
  bboxes: Array<{ x: number; y: number; width: number; height: number }>,
  onProgress?: (percent: number) => void,
): Promise<Blob> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("regions", JSON.stringify(bboxes));

  try {
    const response = await apiClient.post("/api/v1/images/remove-watermark", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      responseType: "blob",
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    });
    return response.data as Blob;
  } catch (error) {
    throw toApiRequestError(error);
  }
}

export async function previewImageDetections(
  file: File,
  detections: object[],
): Promise<string> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("detections", JSON.stringify(detections));

  try {
    const response = await apiClient.post("/api/v1/images/preview", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      responseType: "blob",
    });
    return URL.createObjectURL(response.data as Blob);
  } catch (error) {
    throw toApiRequestError(error);
  }
}
