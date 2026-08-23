"""
Combined text + image watermark removal, done in a single PyMuPDF
document pass (Phase 3 Case A + Phase 4 Case B together).

This exists because chaining remove_text_candidates() and
remove_image_candidates() back-to-back — feeding the first step's
output bytes into the second — is unsafe: PyMuPDF's garbage-collecting
save (`tobytes(garbage=4, ...)`) renumbers PDF object xrefs. An image
candidate's xref, captured at detection time, would then point at the
wrong object (or nothing) in the re-saved intermediate file. Verified
directly: an xref of 8 at detection became 5 after just the text-only
step's save, and the follow-up image lookup failed outright.

The fix is architectural, not a patch: open the document once, apply
every redaction (text quads and image rects) per page, call
apply_redactions() once per page with the right combined scope, and
only save at the very end. No intermediate xrefs are ever produced.
"""
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.watermark import WatermarkCandidate
from app.services.image_remover import ImageRemovalError, _closest_rect
from app.services.text_remover import RemovalError, _closest_quad

_GRAPHICS_UNTOUCHED = fitz.PDF_REDACT_LINE_ART_NONE

# Defense-in-depth: even if detection or a coverage threshold upstream
# misclassifies something, never let automatic removal fully delete an
# image that dominates most of the page — that's Case C content (a
# scan), not a watermark object, and deleting it destroys the page.
# Confirmed directly: a scan with a realistic margin scored below the
# scanned-page coverage threshold, got offered as a removable
# "watermark image candidate", and deleting it blanked the whole page.
# This check catches that failure mode here too, not just by tuning
# one threshold in pdf_analyzer.py.
MAX_AUTO_REMOVAL_COVERAGE = 0.5


def remove_candidates(
    source: Path | bytes,
    candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove a mixed list of text and/or image watermark candidates from
    a PDF in one pass.

    Returns (cleaned_pdf_bytes, pages_affected, skipped_candidate_ids).
    """
    candidates_by_page: dict[int, list[WatermarkCandidate]] = {}
    skipped_candidate_ids: list[str] = []

    for candidate in candidates:
        if pages_filter is not None and candidate.page not in pages_filter:
            skipped_candidate_ids.append(candidate.candidate_id)
            continue
        candidates_by_page.setdefault(candidate.page, []).append(candidate)

    if not candidates_by_page:
        raise RemovalError("NO_CANDIDATES_IN_SCOPE", "None of the selected watermarks are on the requested pages.")

    pages_affected: list[int] = []

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise RemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            for page_number, page_candidates in candidates_by_page.items():
                if page_number < 1 or page_number > pdf.page_count:
                    skipped_candidate_ids.extend(c.candidate_id for c in page_candidates)
                    continue

                page = pdf[page_number - 1]
                has_text = False
                has_image = False

                for candidate in page_candidates:
                    if candidate.type == "text":
                        quad = _closest_quad(page, candidate)
                        if quad is None:
                            skipped_candidate_ids.append(candidate.candidate_id)
                            continue
                        page.add_redact_annot(quad, fill=None)
                        has_text = True
                    else:  # "image"
                        rect = _closest_rect(page, candidate)
                        if rect is None:
                            skipped_candidate_ids.append(candidate.candidate_id)
                            continue

                        page_area = page.rect.width * page.rect.height
                        coverage = (rect.width * rect.height) / page_area if page_area > 0 else 0.0
                        if coverage > MAX_AUTO_REMOVAL_COVERAGE:
                            # Looks like page content, not a watermark —
                            # refuse rather than delete it outright.
                            skipped_candidate_ids.append(candidate.candidate_id)
                            continue

                        page.add_redact_annot(rect, fill=None)
                        has_image = True

                if has_text or has_image:
                    page.apply_redactions(
                        images=fitz.PDF_REDACT_IMAGE_REMOVE if has_image else fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=_GRAPHICS_UNTOUCHED,
                        text=fitz.PDF_REDACT_TEXT_REMOVE if has_text else fitz.PDF_REDACT_TEXT_NONE,
                    )
                    pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except (RemovalError, ImageRemovalError):
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means the file couldn't be processed
        raise RemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected), skipped_candidate_ids
