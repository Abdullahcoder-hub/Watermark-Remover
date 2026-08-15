// Client-side validation is a UX convenience only — the backend
// re-validates every upload (extension, size, and magic bytes) and is
// the actual security boundary.
const MAX_SIZE_MB = 50;

export function validatePdfClientSide(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    return "Only PDF files are supported.";
  }
  if (file.size === 0) {
    return "This file is empty.";
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    return `This file exceeds the ${MAX_SIZE_MB}MB limit.`;
  }
  return null;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
