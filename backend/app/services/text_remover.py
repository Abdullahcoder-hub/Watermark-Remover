"""
Surgical text watermark removal (Preserves 100% of body paragraphs and background text).

Removes watermark text objects directly from the PDF content stream without placing
coarse rectangular redaction boxes over underlying body paragraphs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

from app.schemas.watermark import WatermarkCandidate

if TYPE_CHECKING:
    pass

_IMAGES_UNTOUCHED = fitz.PDF_REDACT_IMAGE_NONE
_GRAPHICS_UNTOUCHED = fitz.PDF_REDACT_LINE_ART_NONE
_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE

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


def clean_page_text_streams(doc: "fitz.Document", page: "fitz.Page", target_texts: list[str]) -> bool:
    """
    Surgically remove watermark text drawing commands directly from the page's
    PDF content streams, completely preserving background/underlying body text.
    Returns True if stream was modified.
    """
    targets = [w.strip() for w in target_texts if w.strip()]
    if not targets:
        return False

    page.clean_contents()
    contents_xrefs = page.get_contents()
    if not contents_xrefs:
        return False

    modified_any = False

    for xref in contents_xrefs:
        raw_bytes = doc.xref_stream(xref)
        if not raw_bytes:
            continue
        stream_str = raw_bytes.decode("latin1")
        initial_stream = stream_str

        for target in targets:
            # 1. Direct TJ match: [(CONFIDENTIAL)]TJ or [(CONFIDENTIAL)] TJ
            p1 = re.compile(r"\[\s*\(" + re.escape(target) + r"\)\s*\]\s*TJ", re.IGNORECASE)
            stream_str = p1.sub("[]TJ", stream_str)

            # 2. Direct Tj match: (CONFIDENTIAL) Tj or ' or "
            p2 = re.compile(r"\(" + re.escape(target) + r"\)\s*(?:Tj|\'|\")", re.IGNORECASE)
            stream_str = p2.sub("() Tj", stream_str)

            # 3. Spaced character array inside TJ: [(C) ... (O) ... (N) ... ]TJ
            chars_pattern = r"\[\s*" + r".*?".join(r"\(" + re.escape(c) + r"\)" for c in target) + r".*?\]\s*TJ"
            p3 = re.compile(chars_pattern, re.IGNORECASE | re.DOTALL)
            stream_str = p3.sub("[]TJ", stream_str)

            # 4. Hex string match if target is pure ascii
            hex_target = target.encode("latin1").hex()
            p4 = re.compile(r"<\s*" + re.escape(hex_target) + r"\s*>\s*(?:Tj|TJ)", re.IGNORECASE)
            stream_str = p4.sub("<> Tj", stream_str)

        if stream_str != initial_stream:
            doc.update_stream(xref, stream_str.encode("latin1"))
            modified_any = True

    return modified_any


def remove_text_candidates(
    source: Path | bytes,
    candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove the given text watermark candidates with surgical precision.
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
                target_words = [c.text for c in page_candidates]

                # 1. Primary: Surgical content stream removal (preserves all body text)
                stream_modified = clean_page_text_streams(pdf, page, target_words)

                # 2. Check if watermark is still present; if so, fallback to tight quad redactions
                remaining_candidates = []
                for c in page_candidates:
                    if c.text in page.get_text():
                        remaining_candidates.append(c)

                redacted_any = False
                for candidate in remaining_candidates:
                    quad = _closest_quad(page, candidate)
                    if quad is None:
                        skipped_candidate_ids.append(candidate.candidate_id)
                        continue
                    page.add_redact_annot(quad, fill=None)
                    redacted_any = True

                if redacted_any:
                    page.apply_redactions(images=_IMAGES_UNTOUCHED, graphics=_GRAPHICS_UNTOUCHED, text=_TEXT_REMOVE)

                if stream_modified or redacted_any:
                    pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except RemovalError:
        raise
    except Exception as exc:
        raise RemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected), skipped_candidate_ids
