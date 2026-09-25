"""
Untrusted-input validation for uploaded PDF and PowerPoint (PPTX) files.

Rules followed here:
- Never trust the client-supplied filename or Content-Type header alone.
- Validate the actual file signature (magic bytes), not just the extension.
- Never build filesystem paths from user-controlled strings.
"""
from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path

# %PDF- is the standard PDF file signature.
PDF_MAGIC_BYTES = b"%PDF-"
# PK\x03\x04 is the standard ZIP file signature used by OpenXML (.pptx)
ZIP_MAGIC_BYTES = b"PK\x03\x04"

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".ppt"}


class FileValidationError(Exception):
    """Raised when an uploaded file fails validation."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def generate_document_id() -> str:
    """Generate a random, non-guessable document identifier."""
    return str(uuid.uuid4())


def is_pdf_signature(header: bytes) -> bool:
    """Check the first bytes of a file against the PDF magic number."""
    return header.startswith(PDF_MAGIC_BYTES)


def is_pptx_signature(header: bytes, contents: bytes | None = None) -> bool:
    """Check if header matches ZIP and contents form a valid PPTX package."""
    if not header.startswith(ZIP_MAGIC_BYTES):
        return False
    if contents is not None and len(contents) > 30:
        try:
            with zipfile.ZipFile(io.BytesIO(contents), "r") as zf:
                namelist = zf.namelist()
                return "ppt/presentation.xml" in namelist or "[Content_Types].xml" in namelist
        except Exception:
            return False
    return True


def get_file_extension(filename: str | None) -> str:
    """Extract and normalize file extension."""
    if not filename:
        return ""
    suffix = Path(filename).suffix.lower()
    return suffix


def validate_upload(
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
    header: bytes,
    max_size_bytes: int,
    full_contents: bytes | None = None,
) -> str:
    """
    Validate an uploaded file before it is persisted to disk.
    Returns normalized extension (e.g. '.pdf' or '.pptx').
    """
    if not filename:
        raise FileValidationError("MISSING_FILENAME", "No filename was provided.")

    ext = get_file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError("INVALID_EXTENSION", "Only PDF and PowerPoint (.pptx) files are supported.")

    if size_bytes <= 0:
        raise FileValidationError("EMPTY_FILE", "The uploaded file is empty.")

    if size_bytes > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise FileValidationError("FILE_TOO_LARGE", f"The uploaded file exceeds the {max_mb}MB limit.")

    if ext == ".pdf":
        if not is_pdf_signature(header):
            raise FileValidationError("INVALID_PDF", "The uploaded file is not a valid PDF.")
        return ".pdf"

    if ext in (".pptx", ".ppt"):
        if not is_pptx_signature(header, full_contents):
            raise FileValidationError("INVALID_PPTX", "The uploaded file is not a valid PowerPoint presentation.")
        return ".pptx"

    raise FileValidationError("INVALID_EXTENSION", "Unsupported file type.")


def safe_document_path(upload_dir: Path, document_id: str, ext: str = ".pdf") -> Path:
    """
    Build a filesystem path for a stored document using only the
    server-generated document_id and safe extension.
    """
    if not ext.startswith("."):
        ext = f".{ext}"
    return upload_dir / f"{document_id}{ext}"


def safe_pdf_path(upload_dir: Path, document_id: str) -> Path:
    """Backward-compatible helper for PDF documents."""
    return safe_document_path(upload_dir, document_id, ".pdf")
