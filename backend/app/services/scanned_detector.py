"""
Scanned page detection (Phase 6, Case C from the project spec).

This is deliberately thin: Phase 2's analyzer already determines
whether a page is scanned (near-zero extractable text plus an image
covering most of the page). This module just answers the follow-up
question Phase 6 needs: *which* image is the scan, so removal knows
whether a page requires pixel-level inpainting (Case C) instead of
object-level redaction (Case A/B).

Why this distinction matters, confirmed empirically: redacting a small
region that only partially overlaps a full-page image does not trim
that region out — it deletes the ENTIRE image object. On a scanned
page, "the image" is the whole page's content, so naive redaction
would destroy the page just because the user boxed a small watermark
stamp in the corner. Inpainting is the only safe removal method here.
"""
from app.schemas.analysis import DocumentAnalysisResponse
from app.services.pdf_analyzer import SCANNED_IMAGE_COVERAGE_THRESHOLD


def scanned_page_xrefs(analysis: DocumentAnalysisResponse) -> dict[int, int]:
    """
    Returns {page_number: xref} for every page the analyzer flagged as
    scanned, identifying the specific image (by xref) that constitutes
    the scan — the one whose coverage triggered the scanned-page
    threshold. Pages without a qualifying image are omitted even if
    flagged scanned (defensive; shouldn't happen given how is_scanned
    is computed, but removal should never guess).
    """
    result: dict[int, int] = {}
    for page in analysis.pages:
        if not page.is_scanned:
            continue
        dominant = max(page.images, key=lambda img: img.coverage_ratio, default=None)
        if dominant is not None and dominant.coverage_ratio >= SCANNED_IMAGE_COVERAGE_THRESHOLD:
            result[page.page_number] = dominant.xref
    return result
