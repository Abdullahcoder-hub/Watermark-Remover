"""
Image watermark removal (Phase 4, Case B from the project spec: a
separate embedded image object watermark).

Removes selected images using PyMuPDF redaction, restricted to the
exact rect the target image occupies, with images=PDF_REDACT_IMAGE_REMOVE
scoped to that redaction area only. Text and vector graphics are left
untouched (text=PDF_REDACT_TEXT_NONE, graphics=PDF_REDACT_LINE_ART_NONE).

Since PDFs commonly reuse the same image object (xref) across several
pages — e.g. a logo watermark placed on every page — removal is always
done per page, using that page's own get_image_rects(xref) lookup, so
selecting "page 1 only" never touches the same image on page 2 even
though it's the same underlying object (verified: PyMuPDF's redaction
removes the page's content-stream reference to the image, not the
shared image object itself, so other pages keep rendering it normally).
"""
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.watermark import WatermarkCandidate

# Redaction scope: only remove the targeted image; never touch text or vector graphics.
_TEXT_UNTOUCHED = fitz.PDF_REDACT_TEXT_NONE
_GRAPHICS_UNTOUCHED = fitz.PDF_REDACT_LINE_ART_NONE
_IMAGES_REMOVE = fitz.PDF_REDACT_IMAGE_REMOVE

_MATCH_TOLERANCE_POINTS = 3.0

# Defense-in-depth: even if detection or a coverage threshold upstream
# misclassifies something, never let automatic removal fully delete an
# image that dominates most of the page — that's Case C content (a
# scan), not a watermark object, and deleting it destroys the page.
# Confirmed directly: a scan with a realistic margin scored below the
# old scanned-page threshold, got offered as a removable "watermark
# image candidate", and deleting it blanked the whole page. This check
# means that failure mode is caught here too, not just by tuning one
# threshold in pdf_analyzer.py.
MAX_AUTO_REMOVAL_COVERAGE = 0.5


class ImageRemovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _closest_rect(page: "fitz.Page", candidate: WatermarkCandidate) -> "fitz.Rect | None":
    """Re-locate the candidate's exact image placement on the page by xref, not stale coordinates."""
    if candidate.xref is None:
        return None

    rects = page.get_image_rects(candidate.xref)
    if not rects:
        return None

    target_x, target_y = _bbox_center(candidate.bbox)
    best_rect = None
    best_distance = float("inf")

    for rect in rects:
        rx, ry = _bbox_center((rect.x0, rect.y0, rect.x1, rect.y1))
        distance = ((rx - target_x) ** 2 + (ry - target_y) ** 2) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_rect = rect

    if best_distance > _MATCH_TOLERANCE_POINTS:
        return None
    return best_rect


def remove_image_candidates(
    source: Path | bytes,
    candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove the given image watermark candidates from a PDF.

    `source` may be a path to a stored PDF, or raw PDF bytes (used when
    chaining this after another removal step in the same /process call).

    Returns (cleaned_pdf_bytes, pages_affected, skipped_candidate_ids).
    A candidate is skipped (not an error) if it falls outside the
    requested page scope, has no xref, or can no longer be precisely
    re-located on the page within tolerance.
    """
    candidates_by_page: dict[int, list[WatermarkCandidate]] = {}
    skipped_candidate_ids: list[str] = []

    for candidate in candidates:
        if pages_filter is not None and candidate.page not in pages_filter:
            skipped_candidate_ids.append(candidate.candidate_id)
            continue
        candidates_by_page.setdefault(candidate.page, []).append(candidate)

    if not candidates_by_page:
        raise ImageRemovalError("NO_CANDIDATES_IN_SCOPE", "None of the selected watermarks are on the requested pages.")

    pages_affected: list[int] = []

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ImageRemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            for page_number, page_candidates in candidates_by_page.items():
                if page_number < 1 or page_number > pdf.page_count:
                    skipped_candidate_ids.extend(c.candidate_id for c in page_candidates)
                    continue

                page = pdf[page_number - 1]
                redacted_any = False

                for candidate in page_candidates:
                    rect = _closest_rect(page, candidate)
                    if rect is None:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue

                    page_area = page.rect.width * page.rect.height
                    coverage = (rect.width * rect.height) / page_area if page_area > 0 else 0.0
                    if coverage > MAX_AUTO_REMOVAL_COVERAGE:
                        # Looks like page content, not a watermark — refuse
                        # rather than delete it outright. Manual selection's
                        # inpainting path is the safe way to handle this.
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue

                    page.add_redact_annot(rect, fill=None)
                    redacted_any = True

                if redacted_any:
                    page.apply_redactions(images=_IMAGES_REMOVE, graphics=_GRAPHICS_UNTOUCHED, text=_TEXT_UNTOUCHED)
                    pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except ImageRemovalError:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means the file couldn't be processed
        raise ImageRemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected), skipped_candidate_ids
