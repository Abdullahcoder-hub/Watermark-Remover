"""
Text watermark removal (Phase 3, Case A from the project spec: a
separate PDF text object watermark).

Removes selected text objects using PyMuPDF redaction, restricted to
text only — images and vector graphics on the page are left untouched
(images=PDF_REDACT_IMAGE_NONE, graphics=PDF_REDACT_LINE_ART_NONE) so
the rest of the document is preserved exactly, per the spec's Case A
requirement and Development Rule 15 ("never silently damage the
original document").

Known limitation (documented, not silently hidden): PyMuPDF's
redaction overlap test uses the axis-aligned bounding box of the
redacted region, not the exact rotated polygon. For a steeply rotated
or oversized watermark whose bounding box happens to sweep over
nearby body text, that body text can be removed together with the
watermark. This is inherent to rectangular/quad-based redaction, not
specific to this implementation. The upcoming preview phase lets users
visually confirm the result before committing to a download.
"""
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.watermark import WatermarkCandidate

# Redaction scope: only remove text; never touch images or vector graphics.
_IMAGES_UNTOUCHED = fitz.PDF_REDACT_IMAGE_NONE
_GRAPHICS_UNTOUCHED = fitz.PDF_REDACT_LINE_ART_NONE
_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE

# How close a re-located quad's center must be to the candidate's
# recorded bbox center to be considered "the same occurrence".
_MATCH_TOLERANCE_POINTS = 3.0


class RemovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _closest_quad(page: "fitz.Page", candidate: WatermarkCandidate) -> "fitz.Quad | None":
    """
    Re-locate the candidate's exact text on the page and return the
    quad whose center is closest to the candidate's recorded bbox
    center — re-finding it rather than trusting stale coordinates,
    since redactions applied earlier in this same run can shift what
    search_for would otherwise return first.
    """
    quads = page.search_for(candidate.text, quads=True)
    if not quads:
        return None

    target_x, target_y = _bbox_center(candidate.bbox)
    best_quad = None
    best_distance = float("inf")

    for quad in quads:
        rect = quad.rect
        qx, qy = _bbox_center((rect.x0, rect.y0, rect.x1, rect.y1))
        distance = ((qx - target_x) ** 2 + (qy - target_y) ** 2) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_quad = quad

    if best_distance > _MATCH_TOLERANCE_POINTS:
        return None
    return best_quad


def remove_text_candidates(
    source: Path | bytes,
    candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove the given text watermark candidates from a PDF.

    `source` may be a path to a stored PDF, or raw PDF bytes (used when
    chaining this after another removal step in the same /process call).

    Returns (cleaned_pdf_bytes, pages_affected, skipped_candidate_ids).
    A candidate is skipped (not an error) either because it falls
    outside the requested page scope, or because its text could no
    longer be precisely re-located on the page within tolerance.
    """
    candidates_by_page: dict[int, list[WatermarkCandidate]] = {}
    out_of_scope_ids: list[str] = []
    for candidate in candidates:
        if pages_filter is not None and candidate.page not in pages_filter:
            out_of_scope_ids.append(candidate.candidate_id)
            continue
        candidates_by_page.setdefault(candidate.page, []).append(candidate)

    if not candidates_by_page:
        raise RemovalError("NO_CANDIDATES_IN_SCOPE", "None of the selected watermarks are on the requested pages.")

    pages_affected: list[int] = []
    skipped_candidate_ids: list[str] = list(out_of_scope_ids)

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise RemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            for page_number, page_candidates in candidates_by_page.items():
                if page_number < 1 or page_number > pdf.page_count:
                    skipped_candidate_ids.extend(c.candidate_id for c in page_candidates)
                    continue

                page = pdf[page_number - 1]
                redacted_any = False

                for candidate in page_candidates:
                    quad = _closest_quad(page, candidate)
                    if quad is None:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue
                    page.add_redact_annot(quad, fill=None)
                    redacted_any = True

                if redacted_any:
                    page.apply_redactions(images=_IMAGES_UNTOUCHED, graphics=_GRAPHICS_UNTOUCHED, text=_TEXT_REMOVE)
                    pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except RemovalError:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means the file couldn't be processed
        raise RemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected), skipped_candidate_ids
