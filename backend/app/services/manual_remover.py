"""
Manual watermark removal (Phase 5).

Unlike the scored, type-scoped automatic detectors, manual selection
is intentionally blunt: the user has visually confirmed a region, so
everything inside it — text, raster images, and vector graphics — is
removed together. This is what catches watermarks the automatic
detectors structurally cannot see, such as a logo drawn with vector
paths rather than an embedded image (confirmed by direct reproduction:
a CamScanner-style "icon" drawn via page.new_shape() has no xref and
is invisible to the Phase 4 image detector).
"""
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.manual import ManualRegion

_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE
_IMAGES_REMOVE = fitz.PDF_REDACT_IMAGE_REMOVE
# "if touched" (not "if covered") because a manually drawn box is a
# deliberate, explicit selection — any graphics the box overlaps
# should go, not only ones fully enclosed by it.
_GRAPHICS_REMOVE = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED


class ManualRemovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _regions_for_document(regions: list[ManualRegion], page_count: int, apply_to_all_pages: bool) -> list[ManualRegion]:
    if not apply_to_all_pages:
        return regions

    expanded: list[ManualRegion] = []
    for region in regions:
        for page_number in range(1, page_count + 1):
            expanded.append(ManualRegion(page=page_number, x0=region.x0, y0=region.y0, x1=region.x1, y1=region.y1))
    return expanded


def remove_manual_regions(
    source: Path | bytes,
    regions: list[ManualRegion],
    apply_to_all_pages: bool,
) -> tuple[bytes, list[int]]:
    """
    Remove everything inside each manually-selected region.

    `source` may be a path to a stored PDF, or raw PDF bytes (used when
    chaining after an earlier automatic-removal step).

    Returns (cleaned_pdf_bytes, pages_affected).
    """
    pages_affected: list[int] = []

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ManualRemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            all_regions = _regions_for_document(regions, pdf.page_count, apply_to_all_pages)

            regions_by_page: dict[int, list[ManualRegion]] = {}
            invalid_pages: set[int] = set()
            for region in all_regions:
                if region.page < 1 or region.page > pdf.page_count:
                    invalid_pages.add(region.page)
                    continue
                regions_by_page.setdefault(region.page, []).append(region)

            if not regions_by_page:
                raise ManualRemovalError("INVALID_PAGE", f"No valid pages in the selection (document has {pdf.page_count} pages).")

            for page_number, page_regions in regions_by_page.items():
                page = pdf[page_number - 1]
                page_width, page_height = page.rect.width, page.rect.height

                for region in page_regions:
                    rect = fitz.Rect(
                        region.x0 * page_width,
                        region.y0 * page_height,
                        region.x1 * page_width,
                        region.y1 * page_height,
                    )
                    if rect.is_empty:
                        continue
                    page.add_redact_annot(rect, fill=None)

                page.apply_redactions(images=_IMAGES_REMOVE, graphics=_GRAPHICS_REMOVE, text=_TEXT_REMOVE)
                pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except ManualRemovalError:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means the file couldn't be processed
        raise ManualRemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected)
