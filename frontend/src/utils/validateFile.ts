// Client-side validation is a UX convenience only — the backend
// re-validates every upload (extension, size, and magic bytes) and is
// the actual security boundary.
const MAX_SIZE_MB = 50;

const ALLOWED_EXTENSIONS = [".pdf", ".pptx", ".ppt"];

export function validatePdfClientSide(file: File): string | null {
  const name = file.name.toLowerCase();
  const isAllowed = ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!isAllowed) {
    return "Only PDF and PowerPoint (.pptx) files are supported.";
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
