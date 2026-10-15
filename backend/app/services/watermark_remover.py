"""
Combined text + image watermark removal.

Uses surgical PDF content stream text removal to preserve 100% of body paragraphs,
headers, and surrounding text without clipping or slicing through overlapping lines.
Includes bounded memory management and progress reporting for large documents.
"""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Callable

import fitz  # PyMuPDF

from app.schemas.watermark import WatermarkCandidate
from app.services.image_remover import ImageRemovalError, _closest_rect
from app.services.text_remover import RemovalError, _closest_quad, clean_page_text_streams

_GRAPHICS_UNTOUCHED = fitz.PDF_REDACT_LINE_ART_NONE
_IMAGES_UNTOUCHED = fitz.PDF_REDACT_IMAGE_NONE
_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE
MAX_AUTO_REMOVAL_COVERAGE = 0.5


def remove_candidates(
    source: Path | bytes,
    candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove a mixed list of text and/or image watermark candidates from
    a PDF in one pass, preserving 100% of non-watermark body text.
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

            total_pages = pdf.page_count
            for page_idx, (page_number, page_candidates) in enumerate(candidates_by_page.items()):
                if progress_callback is not None:
                    progress_callback(
                        page_idx + 1,
                        len(candidates_by_page),
                        f"Removing watermarks — page {page_number} of {total_pages}",
                    )

                if page_number < 1 or page_number > pdf.page_count:
                    skipped_candidate_ids.extend(c.candidate_id for c in page_candidates)
                    continue

                page = pdf[page_number - 1]
                text_candidates = [c for c in page_candidates if c.type == "text"]
                image_candidates = [c for c in page_candidates if c.type == "image"]

                # 1. Surgical stream cleaning for text watermarks
                text_words = [c.text for c in text_candidates]
                stream_modified = clean_page_text_streams(pdf, page, text_words)

                # 2. For any text watermark not removed via stream, fallback to tight quad redaction
                remaining_text = []
                for c in text_candidates:
                    if c.text in page.get_text():
                        remaining_text.append(c)

                has_text_redact = False
                has_image_redact = False

                for candidate in remaining_text:
                    quad = _closest_quad(page, candidate)
                    if quad is None:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue
                    page.add_redact_annot(quad, fill=None)
                    has_text_redact = True

                for candidate in image_candidates:
                    rect = _closest_rect(page, candidate)
                    if rect is None:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue

                    page_area = page.rect.width * page.rect.height
                    coverage = (rect.width * rect.height) / page_area if page_area > 0 else 0.0
                    if coverage > MAX_AUTO_REMOVAL_COVERAGE:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue

                    page.add_redact_annot(rect, fill=None)
                    has_image_redact = True

                # Also check if any selected text watermark is a mobile scanner (e.g. CamScanner)
                # and clean up its accompanying corner logo image if present on the page
                scanner_watermark_selected = any(
                    any(term in c.text.lower() for term in ("camscanner", "scanned with", "adobe scan", "clearscanner"))
                    for c in text_candidates
                )
                if scanner_watermark_selected:
                    page_area = page.rect.width * page.rect.height
                    for img_info in page.get_images(full=True):
                        try:
                            img_rects = page.get_image_rects(img_info[0])
                            for r in img_rects:
                                r_area = r.width * r.height
                                cov = r_area / page_area if page_area > 0 else 0
                                # Small corner logo image
                                if cov < 0.05:
                                    r_x1_frac = r.x1 / page.rect.width
                                    r_y1_frac = r.y1 / page.rect.height
                                    r_x0_frac = r.x0 / page.rect.width
                                    r_y0_frac = r.y0 / page.rect.height
                                    # Located in footer corner
                                    if (r_y1_frac >= 0.80) and (r_x0_frac <= 0.35 or r_x1_frac >= 0.65):
                                        page.add_redact_annot(r, fill=None)
                                        has_image_redact = True
                        except Exception:
                            pass

                if has_text_redact or has_image_redact:
                    page.apply_redactions(
                        images=fitz.PDF_REDACT_IMAGE_REMOVE if has_image_redact else fitz.PDF_REDACT_IMAGE_NONE,
                        graphics=_GRAPHICS_UNTOUCHED,
                        text=fitz.PDF_REDACT_TEXT_REMOVE if has_text_redact else fitz.PDF_REDACT_TEXT_NONE,
                    )

                if stream_modified or has_text_redact or has_image_redact:
                    pages_affected.append(page_number)

                if (page_idx + 1) % 5 == 0:
                    gc.collect()

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except (RemovalError, ImageRemovalError):
        raise
    except Exception as exc:
        raise RemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected), skipped_candidate_ids
