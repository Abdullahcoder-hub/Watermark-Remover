"""
PDF analysis engine (Phase 2).

Extracts structural information from a PDF — text objects, embedded
images, and whether each page is effectively a scanned image — using
PyMuPDF only. This module does not judge which of these might be a
watermark; that scoring is added in Phase 3 (watermark_detector.py)
on top of the data this module produces.

Kept deliberately free of rasterization: pages are inspected via their
object structure, not rendered to images, except to measure image
coverage which uses vector geometry only.
"""
import math
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, PageAnalysis, TextObject

# A page is treated as "scanned" when it has almost no extractable text
# and at least one image that covers most of the page area.
SCANNED_TEXT_LENGTH_THRESHOLD = 20
SCANNED_IMAGE_COVERAGE_THRESHOLD = 0.85


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


def _extract_text_objects(page: "fitz.Page", page_number: int) -> list[TextObject]:
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


def _extract_images(page: "fitz.Page", page_number: int) -> list[ImageObject]:
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


def _analyze_page(page: "fitz.Page", page_number: int) -> PageAnalysis:
    text_objects = _extract_text_objects(page, page_number)
    images = _extract_images(page, page_number)

    extractable_text_length = sum(len(t.text) for t in text_objects)
    max_image_coverage = max((img.coverage_ratio for img in images), default=0.0)
    is_scanned = extractable_text_length < SCANNED_TEXT_LENGTH_THRESHOLD and max_image_coverage >= SCANNED_IMAGE_COVERAGE_THRESHOLD

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


def analyze_document(document_id: str, stored_path: Path) -> DocumentAnalysisResponse:
    """
    Run structural analysis over every page of a stored PDF.

    Raises AnalysisError if the file can't be opened or is encrypted
    (upload-time validation should already have caught these cases,
    but the analyzer re-checks defensively since files are re-opened
    from disk).
    """
    try:
        with fitz.open(stored_path) as pdf:
            if pdf.needs_pass:
                raise AnalysisError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be analyzed.")

            pages = [_analyze_page(pdf[i], i + 1) for i in range(pdf.page_count)]
    except AnalysisError:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means an unreadable/corrupt PDF
        raise AnalysisError("INVALID_PDF", "The document could not be read for analysis.") from exc

    return DocumentAnalysisResponse(
        document_id=document_id,
        page_count=len(pages),
        total_text_objects=sum(p.text_object_count for p in pages),
        total_images=sum(p.image_count for p in pages),
        appears_scanned=any(p.is_scanned for p in pages),
        pages=pages,
    )
