"""
PDF analysis engine (Phase 2 & Upgraded Intelligent Pipeline).

Extracts structural information from a PDF — text objects, embedded
images, rotation, color properties, and whether each page is a scan.

Features:
- Bounded Batching & Memory Safety (analyzes large documents with minimal RAM)
- Real-time Progress Callbacks
- Per-page Failure Resilience (isolated page error handling)
- Explicit Garbage Collection between batches
"""
from __future__ import annotations

import gc
import logging
import math
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, PageAnalysis, TextObject

logger = logging.getLogger("document_cleaner")

SCANNED_TEXT_LENGTH_THRESHOLD = 20
SCANNED_IMAGE_COVERAGE_THRESHOLD = 0.55
ANALYSIS_BATCH_SIZE = 5


class AnalysisError(Exception):
    """Raised when a stored PDF can't be analyzed."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _line_rotation_degrees(line: dict) -> float:
    """Derive a text line's rotation angle (degrees) from its direction vector."""
    dx, dy = line.get("dir", (1.0, 0.0))
    angle = math.degrees(math.atan2(-dy, dx))
    return round(angle % 360, 1)


def _extract_text_objects(page: fitz.Page, page_number: int) -> list[TextObject]:
    objects: list[TextObject] = []
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block, 1 = image block
            continue
        for line in block.get("lines", []):
            rotation = _line_rotation_degrees(line)
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                objects.append(
                    TextObject(
                        text=text,
                        page=page_number,
                        bbox=tuple(round(v, 1) for v in span["bbox"]),
                        font=span.get("font", "unknown"),
                        size=round(span.get("size", 0.0), 1),
                        rotation_degrees=rotation,
                        color=f"#{span.get('color', 0):06x}" if span.get("color") is not None else None,
                    )
                )
    return objects


def _extract_images(page: fitz.Page, page_number: int) -> list[ImageObject]:
    images: list[ImageObject] = []
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return images

    for image_info in page.get_image_info(xrefs=True):
        bbox = image_info.get("bbox")
        if not bbox:
            continue
        width_pt = bbox[2] - bbox[0]
        height_pt = bbox[3] - bbox[1]
        coverage = max(0.0, (width_pt * height_pt) / page_area)

        images.append(
            ImageObject(
                page=page_number,
                xref=int(image_info.get("xref", 0)),
                bbox=tuple(round(v, 1) for v in bbox),
                width=int(image_info.get("width", 0)),
                height=int(image_info.get("height", 0)),
                has_alpha=bool(image_info.get("has-mask", False) or image_info.get("smask", 0)),
                coverage_ratio=round(min(coverage, 1.0), 3),
            )
        )
    return images


def _analyze_page(page: fitz.Page, page_number: int) -> PageAnalysis:
    text_objects = _extract_text_objects(page, page_number)
    images = _extract_images(page, page_number)

    extractable_text_length = sum(len(t.text) for t in text_objects)
    max_image_coverage = max((img.coverage_ratio for img in images), default=0.0)
    is_scanned = (
        extractable_text_length < SCANNED_TEXT_LENGTH_THRESHOLD
        and max_image_coverage >= SCANNED_IMAGE_COVERAGE_THRESHOLD
    )

    return PageAnalysis(
        page_number=page_number,
        width=round(page.rect.width, 1),
        height=round(page.rect.height, 1),
        is_scanned=is_scanned,
        extractable_text_length=extractable_text_length,
        text_object_count=len(text_objects),
        image_count=len(images),
        text_objects=text_objects,
        images=images,
    )


def analyze_document(
    document_id: str,
    stored_path: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> DocumentAnalysisResponse:
    """
    Run structural analysis over every page of a stored PDF using bounded batching.
    Handles small, medium, and 100+ page documents with isolated page error resilience.
    """
    try:
        pdf = fitz.open(stored_path)
    except Exception as exc:
        raise AnalysisError("INVALID_PDF", "The document could not be read for analysis.") from exc

    try:
        if pdf.needs_pass:
            raise AnalysisError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be analyzed.")

        total_pages = pdf.page_count
        pages: list[PageAnalysis] = []
        failed_pages: list[int] = []

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            if progress_callback is not None:
                progress_callback(page_num, total_pages, f"Analyzing PDF — page {page_num} of {total_pages}")

            try:
                page = pdf[page_idx]
                page_analysis = _analyze_page(page, page_num)
                pages.append(page_analysis)
            except Exception as page_exc:
                logger.warning("page_analysis_failed doc=%s page=%s: %s", document_id, page_num, page_exc)
                failed_pages.append(page_num)
                # Fallback empty page analysis to keep document intact
                pages.append(
                    PageAnalysis(
                        page_number=page_num,
                        width=595.0,
                        height=842.0,
                        is_scanned=False,
                        extractable_text_length=0,
                        text_object_count=0,
                        image_count=0,
                        has_error=True,
                        error_message=str(page_exc),
                    )
                )

            # Memory management: run gc between batches
            if page_num % ANALYSIS_BATCH_SIZE == 0:
                gc.collect()

    finally:
        pdf.close()
        gc.collect()

    total_scanned = total_pages - len(failed_pages)

    return DocumentAnalysisResponse(
        document_id=document_id,
        page_count=len(pages),
        total_text_objects=sum(p.text_object_count for p in pages),
        total_images=sum(p.image_count for p in pages),
        appears_scanned=any(p.is_scanned for p in pages),
        pages=pages,
        total_scanned=total_scanned,
        failed_pages=failed_pages,
    )
