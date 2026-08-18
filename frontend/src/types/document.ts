export interface DocumentUploadResponse {
  success: true;
  document_id: string;
  original_filename: string;
  size_bytes: number;
  page_count: number | null;
  uploaded_at: string;
  status: string;
}

export interface ApiErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
  };
}

export interface TextObject {
  text: string;
  page: number;
  bbox: [number, number, number, number];
  font: string;
  size: number;
  rotation_degrees: number;
  color: string | null;
}

export interface ImageObject {
  page: number;
  xref: number;
  bbox: [number, number, number, number];
  width: number;
  height: number;
  has_alpha: boolean;
  coverage_ratio: number;
}

export interface PageAnalysis {
  page_number: number;
  width: number;
  height: number;
  is_scanned: boolean;
  extractable_text_length: number;
  text_object_count: number;
  image_count: number;
  text_objects: TextObject[];
  images: ImageObject[];
}

export interface DocumentAnalysisResponse {
  success: true;
  document_id: string;
  page_count: number;
  total_text_objects: number;
  total_images: number;
  appears_scanned: boolean;
  pages: PageAnalysis[];
}

export interface WatermarkCandidate {
  candidate_id: string;
  type: "text" | "image";
  text: string;
  page: number;
  bbox: [number, number, number, number];
  rotation_degrees: number;
  confidence: number;
  reasons: string[];
  xref: number | null;
}

export interface DetectionResponse {
  success: true;
  document_id: string;
  candidate_count: number;
  candidates: WatermarkCandidate[];
}

export interface ProcessResponse {
  success: true;
  document_id: string;
  status: string;
  requested_count: number;
  removed_count: number;
  skipped_candidate_ids: string[];
  pages_affected: number[];
}

