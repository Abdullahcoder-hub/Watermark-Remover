"""
Untrusted-input validation for uploaded files.

Rules followed here (see project security rules):
- Never trust the client-supplied filename or Content-Type header alone.
- Validate the actual file signature (magic bytes), not just the extension.
- Never build filesystem paths from user-controlled strings.
"""
import uuid

# %PDF- is the standard PDF file signature.
PDF_MAGIC_BYTES = b"%PDF-"


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


def validate_upload(filename: str | None, content_type: str | None, size_bytes: int, header: bytes, max_size_bytes: int) -> None:
    """
    Validate an uploaded file before it is persisted to disk.

    Raises FileValidationError with a machine-readable code on failure.
    The original filename/content_type are used only for user-facing
    messages and are never used to construct a filesystem path.
    """
    if not filename:
        raise FileValidationError("MISSING_FILENAME", "No filename was provided.")

    if not filename.lower().endswith(".pdf"):
        raise FileValidationError("INVALID_EXTENSION", "Only PDF files are supported.")

    if size_bytes <= 0:
        raise FileValidationError("EMPTY_FILE", "The uploaded file is empty.")

    if size_bytes > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise FileValidationError("FILE_TOO_LARGE", f"The uploaded file exceeds the {max_mb}MB limit.")

    if not is_pdf_signature(header):
        raise FileValidationError("INVALID_PDF", "The uploaded file is not a valid PDF.")


def safe_pdf_path(upload_dir, document_id: str):
    """
    Build a filesystem path for a stored document using only the
    server-generated document_id — never the client-supplied filename.
    """
    return upload_dir / f"{document_id}.pdf"
