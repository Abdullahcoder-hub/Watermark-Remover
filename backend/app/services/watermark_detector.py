"""
Watermark candidate detector (Phase 3).

Takes a Phase 2 DocumentAnalysisResponse (raw text/image structure)
and scores which text objects look like watermarks. This is a
heuristic MVP — it does not decide anything on its own; every
candidate, however high its confidence, waits for the user to select
it before /process removes it.

Scoring factors (see project spec Section 3):
  - repeated across multiple pages
  - rotated (diagonal watermarks are rotated; body text normally isn't)
  - matches common watermark wording (CONFIDENTIAL, DRAFT, SAMPLE, ...)
  - large relative to the page (watermark text is often oversized)

Each factor contributes a fixed weight; the total is capped at 1.0.
Image-based and scanned-region candidates are added in later phases.
"""
import uuid
from collections import defaultdict

from app.schemas.analysis import DocumentAnalysisResponse, TextObject
from app.schemas.watermark import WatermarkCandidate

COMMON_WATERMARK_WORDS = {
    "confidential",
    "draft",
    "sample",
    "copy",
    "void",
    "watermark",
    "proof",
    "do not distribute",
    "not for distribution",
    "internal use only",
    "preliminary",
}

REPETITION_WEIGHT = 0.4
ROTATION_WEIGHT = 0.3
KEYWORD_WEIGHT = 0.2
SIZE_WEIGHT = 0.1

ROTATION_TOLERANCE_DEGREES = 1.0
LARGE_TEXT_HEIGHT_RATIO = 0.05  # span height vs. page height
MIN_PAGES_FOR_REPETITION = 2


def _is_rotated(rotation_degrees: float) -> bool:
    normalized = rotation_degrees % 360
    return min(normalized, 360 - normalized) > ROTATION_TOLERANCE_DEGREES


def _matches_watermark_wording(normalized_text: str) -> bool:
    return any(word in normalized_text for word in COMMON_WATERMARK_WORDS)


def generate_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
    page_heights = {page.page_number: page.height for page in analysis.pages}

    occurrences_by_text: dict[str, list[TextObject]] = defaultdict(list)
    for page in analysis.pages:
        for obj in page.text_objects:
            normalized = obj.text.strip().lower()
            if normalized:
                occurrences_by_text[normalized].append(obj)

    candidates: list[WatermarkCandidate] = []

    for normalized_text, occurrences in occurrences_by_text.items():
        pages_with_text = {o.page for o in occurrences}
        is_repeated = len(pages_with_text) >= MIN_PAGES_FOR_REPETITION

        for obj in occurrences:
            score = 0.0
            reasons: list[str] = []

            if is_repeated:
                score += REPETITION_WEIGHT
                reasons.append(f"same text appears on {len(pages_with_text)} pages")

            if _is_rotated(obj.rotation_degrees):
                score += ROTATION_WEIGHT
                reasons.append(f"rotated {obj.rotation_degrees}°")

            if _matches_watermark_wording(normalized_text):
                score += KEYWORD_WEIGHT
                reasons.append("matches common watermark wording")

            page_height = page_heights.get(obj.page, 0.0)
            span_height = obj.bbox[3] - obj.bbox[1]
            if page_height > 0 and (span_height / page_height) > LARGE_TEXT_HEIGHT_RATIO:
                score += SIZE_WEIGHT
                reasons.append("large relative to the page")

            if score <= 0:
                continue  # no signal at all — not worth surfacing as a candidate

            candidates.append(
                WatermarkCandidate(
                    candidate_id=str(uuid.uuid4()),
                    type="text",
                    text=obj.text,
                    page=obj.page,
                    bbox=obj.bbox,
                    rotation_degrees=obj.rotation_degrees,
                    confidence=round(min(score, 1.0), 2),
                    reasons=reasons,
                )
            )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates
