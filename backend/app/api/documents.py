"""
Document upload, analysis, detection, processing, preview, and download endpoints.

Supports both PDF and PowerPoint (PPTX) documents:
- PDF: Object-level PyMuPDF text & image redaction, OpenCV scanned inpainting, OCR.
- PPTX: OpenXML shape, text, layout, and slide-master watermark inspection and removal.
- Watermark Detection: Tokenless heuristic AI pattern recognition covering CamScanner,
  Gamma App, Canva, Adobe Scan, WPS, Tome, PDF utilities, and confidential/draft stamps.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.schemas.analysis import DocumentAnalysisResponse
from app.schemas.document import DocumentUploadResponse
from app.schemas.manual import ManualRemovalRequest, ManualRemovalResponse
from app.schemas.ocr import OcrPageResult, OcrRequest, OcrResponse
from app.schemas.processing import ProcessRequest, ProcessResponse
from app.schemas.watermark import DetectionResponse, WatermarkCandidate
from app.services.cleanup_service import delete_document
from app.services.image_remover import ImageRemovalError
from app.services.manual_remover import ManualRemovalError, remove_manual_regions
from app.services.ocr_service import OcrError, add_ocr_text_layer
from app.services.pdf_analyzer import AnalysisError, analyze_document
from app.services.pptx_processor import (
    PptxProcessingError,
    analyze_pptx,
    get_pptx_slide_count,
    is_pptx_file,
    remove_pptx_watermarks,
    render_pptx_slide_preview,
)
from app.services.scanned_detector import scanned_page_xrefs
from app.services.text_remover import RemovalError
from app.services.watermark_detector import generate_candidates
from app.services.watermark_remover import remove_candidates
from app.utils.document_store import DocumentRecord, analysis_store, detection_store, document_store, preview_cache, utcnow
from app.utils.file_validation import (
    FileValidationError,
    generate_document_id,
    get_file_extension,
    safe_document_path,
    validate_upload,
)

logger = logging.getLogger("document_cleaner")

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

MAGIC_BYTES_READ_LENGTH = 8
PREVIEW_DPI = 120


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"success": False, "error": {"code": code, "message": message}})


def _is_pptx(record: "DocumentRecord") -> bool:
    """Determine if a document is a PowerPoint presentation."""
    if record.original_filename and record.original_filename.lower().endswith((".pptx", ".ppt")):
        return True
    if record.stored_path and record.stored_path.lower().endswith(".pptx"):
        return True
    return False


def _current_source_path(record: "DocumentRecord") -> Path:
    """
    The most up-to-date version of a document: its processed result if
    any removal has already run, otherwise the original upload.
    """
    if record.result_path and Path(record.result_path).exists():
        return Path(record.result_path)
    return Path(record.stored_path)


def _get_or_run_analysis(document_id: str, record: "DocumentRecord") -> DocumentAnalysisResponse:
    """Retrieve cached analysis or run fresh structural analysis."""
    analysis = analysis_store.get(document_id)
    if analysis is None:
        source_path = _current_source_path(record)
        try:
            if _is_pptx(record):
                analysis = analyze_pptx(document_id, source_path)
            else:
                analysis = analyze_document(document_id, source_path)
        except (AnalysisError, PptxProcessingError) as exc:
            raise _api_error(400, exc.code, exc.message) from exc
        analysis_store.set(document_id, analysis)
    return analysis  # type: ignore[return-value]


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentUploadResponse:
    contents = await file.read()
    header = contents[:MAGIC_BYTES_READ_LENGTH]

    try:
        ext = validate_upload(
            filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(contents),
            header=header,
            max_size_bytes=settings.max_upload_size_bytes,
            full_contents=contents,
        )
    except FileValidationError as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    document_id = generate_document_id()
    stored_path = safe_document_path(settings.upload_path, document_id, ext)

    try:
        stored_path.write_bytes(contents)
    except OSError as exc:
        logger.error("upload_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The file could not be saved. Please try again.") from exc

    page_count: int | None = None

    if ext == ".pptx":
        try:
            page_count = get_pptx_slide_count(stored_path)
        except Exception as exc:
            stored_path.unlink(missing_ok=True)
            logger.warning("upload_unreadable_pptx job_id=%s: %s", document_id, exc)
            raise _api_error(400, "INVALID_PPTX", "The uploaded file is not a readable PowerPoint presentation.") from exc
    else:
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
        except Exception as exc:
            stored_path.unlink(missing_ok=True)
            logger.warning("upload_unreadable_pdf job_id=%s", document_id)
            raise _api_error(400, "INVALID_PDF", "The uploaded file is not a valid or readable PDF.") from exc

    if page_count is not None and page_count > settings.max_pages:
        stored_path.unlink(missing_ok=True)
        raise _api_error(
            400,
            "PAGE_LIMIT_EXCEEDED",
            f"The document exceeds the maximum limit of {settings.max_pages} pages (has {page_count} pages).",
        )

    record = DocumentRecord(
        document_id=document_id,
        original_filename=file.filename or f"document{ext}",
        size_bytes=len(contents),
        page_count=page_count,
        uploaded_at=utcnow(),
        stored_path=str(stored_path),
    )
    document_store.add(record)

    logger.info("upload_success job_id=%s size_bytes=%s pages=%s type=%s", document_id, record.size_bytes, page_count, ext)

    return DocumentUploadResponse(
        document_id=document_id,
        original_filename=record.original_filename,
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
        source_path = Path(record.stored_path)
        if _is_pptx(record):
            result = analyze_pptx(document_id, source_path)
        else:
            result = analyze_document(document_id, source_path)
    except (AnalysisError, PptxProcessingError) as exc:
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

    analysis = _get_or_run_analysis(document_id, record)
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

    source_path = _current_source_path(record)
    is_ppt = _is_pptx(record)

    try:
        if is_ppt:
            cleaned_bytes, pages_affected, skipped_ids = remove_pptx_watermarks(source_path, selected, pages_filter)
            result_path = settings.result_path / f"{document_id}.pptx"
        else:
            cleaned_bytes, pages_affected, skipped_ids = remove_candidates(source_path, selected, pages_filter)
            result_path = settings.result_path / f"{document_id}.pdf"
    except (RemovalError, ImageRemovalError, PptxProcessingError) as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    try:
        result_path.write_bytes(cleaned_bytes)
    except OSError as exc:
        logger.error("process_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The cleaned file could not be saved. Please try again.") from exc

    document_store.set_result_path(document_id, str(result_path))
    document_store.set_status(document_id, "processed")
    analysis_store.delete(document_id)

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


def _safe_download_filename(original_filename: str, ext: str = ".pdf") -> str:
    """Build a Content-Disposition-safe filename derived from the original name."""
    stem = Path(original_filename).stem
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "document"
    return f"cleaned_{safe_stem}{ext}"


@router.get("/{document_id}/download")
async def download_document(document_id: str) -> FileResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    if not record.result_path:
        raise _api_error(400, "NOT_PROCESSED", "This document has not been processed yet.")

    res_path = Path(record.result_path).resolve()
    allowed_dirs = [settings.result_path.resolve(), settings.upload_path.resolve()]
    if not any(res_path.is_relative_to(d) for d in allowed_dirs) or not res_path.exists():
        logger.warning("unauthorized_path_access job_id=%s path=%s", document_id, record.result_path)
        raise _api_error(404, "FILE_NOT_FOUND", "The requested document file could not be found.")

    is_ppt = _is_pptx(record)
    media_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if is_ppt
        else "application/pdf"
    )
    download_ext = ".pptx" if is_ppt else ".pdf"

    return FileResponse(
        path=str(res_path),
        media_type=media_type,
        filename=_safe_download_filename(record.original_filename, download_ext),
    )


@router.get("/{document_id}/preview/{page_number}")
async def preview_page(document_id: str, page_number: int, version: str = "current") -> Response:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    if version not in ("current", "original"):
        raise _api_error(400, "INVALID_VERSION", "version must be 'current' or 'original'.")

    source_path = Path(record.stored_path) if version == "original" else _current_source_path(record)
    source_resolved = source_path.resolve()
    allowed_dirs = [settings.result_path.resolve(), settings.upload_path.resolve()]
    if not any(source_resolved.is_relative_to(d) for d in allowed_dirs) or not source_resolved.exists():
        raise _api_error(404, "FILE_NOT_FOUND", "The source document file could not be found.")

    try:
        mtime = source_resolved.stat().st_mtime
    except OSError:
        mtime = 0.0

    cached = preview_cache.get(document_id, page_number, mtime)
    if cached is not None:
        return Response(content=cached, media_type="image/jpeg")

    is_ppt = _is_pptx(record)

    if is_ppt:
        try:
            image_bytes = render_pptx_slide_preview(source_path, page_number)
        except Exception as exc:
            logger.error("preview_failed_pptx job_id=%s slide=%s: %s", document_id, page_number, exc)
            raise _api_error(500, "PREVIEW_FAILED", "This PowerPoint slide could not be rendered.") from exc
    else:
        try:
            with fitz.open(source_path) as pdf:
                if page_number < 1 or page_number > pdf.page_count:
                    raise _api_error(400, "INVALID_PAGE", f"This document has {pdf.page_count} pages.")
                page = pdf[page_number - 1]
                zoom = PREVIEW_DPI / 72
                pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                image_bytes = pixmap.tobytes("jpg", jpg_quality=85)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("preview_failed job_id=%s page=%s version=%s", document_id, page_number, version)
            raise _api_error(500, "PREVIEW_FAILED", "This page could not be rendered.") from exc

    preview_cache.set(document_id, page_number, mtime, image_bytes)
    return Response(content=image_bytes, media_type="image/jpeg")


@router.post("/{document_id}/manual-remove", response_model=ManualRemovalResponse)
async def manual_remove(document_id: str, request: ManualRemovalRequest) -> ManualRemovalResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    for region in request.regions:
        if region.x1 <= region.x0 or region.y1 <= region.y0:
            raise _api_error(400, "INVALID_REGION", "Each region's x1/y1 must be greater than its x0/y0.")

    source_path = _current_source_path(record)

    try:
        fresh_analysis = analyze_document(document_id, source_path)
    except AnalysisError as exc:
        raise _api_error(400, exc.code, exc.message) from exc
    scanned_pages = scanned_page_xrefs(fresh_analysis)

    try:
        cleaned_bytes, pages_affected = remove_manual_regions(
            source_path, request.regions, request.apply_to_all_pages, scanned_pages
        )
    except ManualRemovalError as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    result_path = settings.result_path / f"{document_id}.pdf"
    try:
        result_path.write_bytes(cleaned_bytes)
    except OSError as exc:
        logger.error("manual_remove_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The cleaned file could not be saved. Please try again.") from exc

    document_store.set_result_path(document_id, str(result_path))
    document_store.set_status(document_id, "processed")
    analysis_store.delete(document_id)

    logger.info(
        "manual_remove_success job_id=%s regions=%s pages_affected=%s",
        document_id,
        len(request.regions),
        pages_affected,
    )

    return ManualRemovalResponse(
        document_id=document_id,
        regions_applied=len(request.regions),
        pages_affected=pages_affected,
    )


@router.post("/{document_id}/ocr", response_model=OcrResponse)
async def ocr_document(document_id: str, request: OcrRequest) -> OcrResponse:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    if record.ocr_applied and not request.pages:
        return OcrResponse(document_id=document_id, pages_ocred=[], already_applied=True)

    source_path = _current_source_path(record)

    if request.pages:
        target_pages = request.pages
    else:
        analysis = _get_or_run_analysis(document_id, record)
        target_pages = [p.page_number for p in analysis.pages if p.is_scanned]

    if not target_pages:
        return OcrResponse(document_id=document_id, pages_ocred=[], already_applied=record.ocr_applied)

    try:
        ocr_bytes, words_by_page = add_ocr_text_layer(source_path, target_pages)
    except OcrError as exc:
        raise _api_error(400, exc.code, exc.message) from exc

    result_path = settings.result_path / f"{document_id}.pdf"
    try:
        result_path.write_bytes(ocr_bytes)
    except OSError as exc:
        logger.error("ocr_write_failed job_id=%s", document_id)
        raise _api_error(500, "STORAGE_ERROR", "The OCR'd file could not be saved. Please try again.") from exc

    document_store.set_result_path(document_id, str(result_path))
    document_store.set_status(document_id, "processed")
    document_store.set_ocr_applied(document_id, True)
    analysis_store.delete(document_id)

    logger.info("ocr_success job_id=%s pages=%s", document_id, list(words_by_page.keys()))

    return OcrResponse(
        document_id=document_id,
        pages_ocred=[OcrPageResult(page=page, words_added=count) for page, count in sorted(words_by_page.items())],
    )


@router.delete("/{document_id}")
async def delete_document_route(document_id: str) -> dict:
    record = document_store.get(document_id)
    if record is None:
        raise _api_error(404, "DOCUMENT_NOT_FOUND", "No document was found with that ID.")

    delete_document(record)

    return {"success": True, "document_id": document_id, "status": "deleted"}
