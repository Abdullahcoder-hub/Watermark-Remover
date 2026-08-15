"""
Document upload and analysis endpoints.

Phase 1: upload + validation + safe temporary storage.
Phase 2: analysis (text extraction, image detection, scanned-page
detection) is added on top of Phase 1's upload flow.
"""
import logging
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.schemas.analysis import DocumentAnalysisResponse
from app.schemas.document import DocumentUploadResponse
from app.services.pdf_analyzer import AnalysisError, analyze_document
from app.utils.document_store import DocumentRecord, analysis_store, document_store, utcnow
from app.utils.file_validation import FileValidationError, generate_document_id, safe_pdf_path, validate_upload

logger = logging.getLogger("document_cleaner")

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# Only the first few bytes are needed to check the PDF magic number.
MAGIC_BYTES_READ_LENGTH = 8


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"success": False, "error": {"code": code, "message": message}})


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    contents = await file.read()
    header = contents[:MAGIC_BYTES_READ_LENGTH]

    try:
        validate_upload(
            filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(contents),
            header=header,
            max_size_bytes=settings.max_upload_size_bytes,
        )
    except FileValidationError as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    document_id = generate_document_id()
    stored_path = safe_pdf_path(settings.upload_path, document_id)

    try:
        stored_path.write_bytes(contents)
    except OSError as exc:
        logger.error("upload_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The file could not be saved. Please try again.") from exc

    page_count = None
    try:
        with fitz.open(stored_path) as pdf:
            if pdf.needs_pass:
                stored_path.unlink(missing_ok=True)
                raise _api_error(
                    400,
                    "PASSWORD_PROTECTED",
                    "This PDF is password-protected. Please unlock it before uploading.",
                )
            page_count = pdf.page_count
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means an unreadable/corrupt PDF
        stored_path.unlink(missing_ok=True)
        logger.warning("upload_unreadable_pdf job_id=%s", document_id)
        raise _api_error(400, "INVALID_PDF", "The uploaded file is not a valid or readable PDF.") from exc

    record = DocumentRecord(
        document_id=document_id,
        original_filename=file.filename,
        size_bytes=len(contents),
        page_count=page_count,
        uploaded_at=utcnow(),
        stored_path=str(stored_path),
    )
    document_store.add(record)

    logger.info("upload_success job_id=%s size_bytes=%s pages=%s", document_id, record.size_bytes, page_count)

    return DocumentUploadResponse(
        document_id=document_id,
        original_filename=file.filename,
        size_bytes=record.size_bytes,
        page_count=page_count,
        uploaded_at=record.uploaded_at,
        status=record.status,
    )


@router.post("/{document_id}/analyze", response_model=DocumentAnalysisResponse)
async def analyze_document_route(document_id: str) -> DocumentAnalysisResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    document_store.set_status(document_id, "analyzing")

    try:
        result = analyze_document(document_id, Path(record.stored_path))
    except AnalysisError as exc:
        document_store.set_status(document_id, "uploaded")
        raise _api_error(400, exc.code, exc.message) from exc

    analysis_store.set(document_id, result)
    document_store.set_status(document_id, "analyzed")

    logger.info(
        "analyze_success job_id=%s pages=%s text_objects=%s images=%s scanned=%s",
        document_id,
        result.page_count,
        result.total_text_objects,
        result.total_images,
        result.appears_scanned,
    )

    return result


@router.get("/{document_id}/status")
async def get_document_status(document_id: str) -> dict:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    return {
        "success": True,
        "document_id": document_id,
        "status": record.status,
        "original_filename": record.original_filename,
        "page_count": record.page_count,
    }
