"""
Document upload, analysis, detection, processing, and download endpoints.

Phase 1: upload + validation + safe temporary storage.
Phase 2: analysis (text extraction, image detection, scanned-page
detection) on top of Phase 1's upload flow.
Phase 3: watermark candidate detection (text only) and removal via
redaction, plus the download endpoint needed to retrieve the result.
"""
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.schemas.analysis import DocumentAnalysisResponse
from app.schemas.document import DocumentUploadResponse
from app.schemas.processing import ProcessRequest, ProcessResponse
from app.schemas.watermark import DetectionResponse, WatermarkCandidate
from app.services.pdf_analyzer import AnalysisError, analyze_document
from app.services.text_remover import RemovalError, remove_text_candidates
from app.services.watermark_detector import generate_candidates
from app.utils.document_store import DocumentRecord, analysis_store, detection_store, document_store, utcnow
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


@router.post("/{document_id}/detect", response_model=DetectionResponse)
async def detect_watermarks(document_id: str) -> DetectionResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    analysis = analysis_store.get(document_id)
    if analysis is None:
        # /detect depends on analysis but is convenient to call on its
        # own — run it automatically rather than making the caller
        # sequence two requests for one logical step.
        try:
            analysis = analyze_document(document_id, Path(record.stored_path))
        except AnalysisError as exc:
            raise _api_error(400, exc.code, exc.message) from exc
        analysis_store.set(document_id, analysis)

    candidates = generate_candidates(analysis)
    detection_store.set(document_id, candidates)
    document_store.set_status(document_id, "detected")

    logger.info("detect_success job_id=%s candidate_count=%s", document_id, len(candidates))

    return DetectionResponse(document_id=document_id, candidate_count=len(candidates), candidates=candidates)


@router.post("/{document_id}/process", response_model=ProcessResponse)
async def process_document(document_id: str, request: ProcessRequest) -> ProcessResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    cached_candidates: list[WatermarkCandidate] | None = detection_store.get(document_id)  # type: ignore[assignment]
    if not cached_candidates:
        raise _api_error(400, "NO_CANDIDATES_DETECTED", "Run watermark detection before processing this document.")

    candidates_by_id = {c.candidate_id: c for c in cached_candidates}
    selected: list[WatermarkCandidate] = []
    unknown_ids: list[str] = []
    for candidate_id in request.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            unknown_ids.append(candidate_id)
        else:
            selected.append(candidate)

    if not selected:
        raise _api_error(400, "INVALID_CANDIDATE_IDS", "None of the given candidate IDs match this document's detected watermarks.")

    if request.pages == "current":
        if request.current_page is None:
            raise _api_error(400, "MISSING_CURRENT_PAGE", "current_page is required when pages is 'current'.")
        pages_filter: set[int] | None = {request.current_page}
    elif request.pages == "selected":
        if not request.selected_pages:
            raise _api_error(400, "MISSING_SELECTED_PAGES", "selected_pages is required when pages is 'selected'.")
        pages_filter = set(request.selected_pages)
    else:
        pages_filter = None  # "all"

    try:
        cleaned_bytes, pages_affected, skipped_ids = remove_text_candidates(
            Path(record.stored_path), selected, pages_filter
        )
    except RemovalError as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    result_path = settings.result_path / f"{document_id}.pdf"
    try:
        result_path.write_bytes(cleaned_bytes)
    except OSError as exc:
        logger.error("process_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The cleaned file could not be saved. Please try again.") from exc

    document_store.set_result_path(document_id, str(result_path))
    document_store.set_status(document_id, "processed")

    all_skipped = sorted(set(skipped_ids) | set(unknown_ids))
    removed_count = len(request.candidate_ids) - len(all_skipped)

    logger.info(
        "process_success job_id=%s requested=%s removed=%s pages_affected=%s",
        document_id,
        len(request.candidate_ids),
        removed_count,
        pages_affected,
    )

    return ProcessResponse(
        document_id=document_id,
        requested_count=len(request.candidate_ids),
        removed_count=removed_count,
        skipped_candidate_ids=all_skipped,
        pages_affected=pages_affected,
    )


def _safe_download_filename(original_filename: str) -> str:
    """Build a Content-Disposition-safe filename derived from the original name."""
    stem = Path(original_filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "document"
    return f"cleaned_{safe_stem}.pdf"


@router.get("/{document_id}/download")
async def download_document(document_id: str) -> FileResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    if not record.result_path or not Path(record.result_path).exists():
        raise _api_error(400, "NOT_PROCESSED", "This document has not been processed yet.")

    return FileResponse(
        path=record.result_path,
        media_type="application/pdf",
        filename=_safe_download_filename(record.original_filename),
    )
