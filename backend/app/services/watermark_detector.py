"""
Watermark candidate detector (Phase 3: text, Phase 4: images).

Takes a Phase 2 DocumentAnalysisResponse (raw text/image structure)
and scores which text objects and embedded images look like
watermarks. This is a heuristic MVP — it does not decide anything on
its own; every candidate, however high its confidence, waits for the
user to select it before /process removes it.

Text scoring factors (see project spec Section 3):
  - repeated across multiple pages
  - rotated (diagonal watermarks are rotated; body text normally isn't)
  - matches common watermark wording (CONFIDENTIAL, DRAFT, SAMPLE, ...)
  - large relative to the page (watermark text is often oversized)

Image scoring factors:
  - the same embedded image (same xref) reused across multiple pages
  - has an alpha channel / soft mask (watermark overlays are usually
    semi-transparent so the underlying content stays legible)
  - moderate size relative to the page (a logo or stamp, not the
    page's main content — full-page images are excluded here since
    Phase 2 already flags those as "scanned", i.e. likely the actual
    document content rather than an overlay)
  - roughly centered on the page (a common watermark placement)

Each factor contributes a fixed weight; the total is capped at 1.0.
Scanned-region candidates (Case C documents) are added in a later phase.
"""
import uuid
from collections import defaultdict

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, TextObject
from app.schemas.watermark import WatermarkCandidate
from app.services.pdf_analyzer import SCANNED_IMAGE_COVERAGE_THRESHOLD

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

TEXT_REPETITION_WEIGHT = 0.4
ROTATION_WEIGHT = 0.3
KEYWORD_WEIGHT = 0.2
SIZE_WEIGHT = 0.1

ROTATION_TOLERANCE_DEGREES = 1.0
LARGE_TEXT_HEIGHT_RATIO = 0.05  # span height vs. page height
MIN_PAGES_FOR_REPETITION = 2

IMAGE_REPETITION_WEIGHT = 0.4
TRANSPARENCY_WEIGHT = 0.3
MODERATE_SIZE_WEIGHT = 0.2
CENTERED_WEIGHT = 0.1

# An image below this coverage is treated as decorative noise (e.g. a
# tiny bullet icon) rather than a plausible watermark.
MIN_WATERMARK_IMAGE_COVERAGE = 0.02
# At/above this coverage an image is almost certainly the page's main
# content (this matches the analyzer's own "scanned page" threshold),
# not an overlay — excluded from image watermark candidates entirely.
MAX_WATERMARK_IMAGE_COVERAGE = SCANNED_IMAGE_COVERAGE_THRESHOLD
# How close to page-center (as a fraction of page width/height) an
# image's center must fall to count as "centered".
CENTERED_TOLERANCE_FRACTION = 0.35


def _is_rotated(rotation_degrees: float) -> bool:
    normalized = rotation_degrees % 360
    return min(normalized, 360 - normalized) > ROTATION_TOLERANCE_DEGREES


def _matches_watermark_wording(normalized_text: str) -> bool:
    return any(word in normalized_text for word in COMMON_WATERMARK_WORDS)


def _generate_text_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
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
                score += TEXT_REPETITION_WEIGHT
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

    return candidates


def _is_centered(bbox: tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    if page_width <= 0 or page_height <= 0:
        return False
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    x_offset = abs(cx - page_width / 2) / page_width
    y_offset = abs(cy - page_height / 2) / page_height
    return x_offset <= CENTERED_TOLERANCE_FRACTION and y_offset <= CENTERED_TOLERANCE_FRACTION


def _generate_image_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
    page_dims = {page.page_number: (page.width, page.height) for page in analysis.pages}

    occurrences_by_xref: dict[int, list[ImageObject]] = defaultdict(list)
    for page in analysis.pages:
        for img in page.images:
            if MIN_WATERMARK_IMAGE_COVERAGE <= img.coverage_ratio < MAX_WATERMARK_IMAGE_COVERAGE:
                occurrences_by_xref[img.xref].append(img)

    candidates: list[WatermarkCandidate] = []

    for xref, occurrences in occurrences_by_xref.items():
        pages_with_image = {o.page for o in occurrences}
        is_repeated = len(pages_with_image) >= MIN_PAGES_FOR_REPETITION

        for img in occurrences:
            score = 0.0
            reasons: list[str] = []

            if is_repeated:
                score += IMAGE_REPETITION_WEIGHT
                reasons.append(f"same image appears on {len(pages_with_image)} pages")

            if img.has_alpha:
                score += TRANSPARENCY_WEIGHT
                reasons.append("has transparency, typical of watermark overlays")

            score += MODERATE_SIZE_WEIGHT
            reasons.append("moderate size relative to the page")

            page_width, page_height = page_dims.get(img.page, (0.0, 0.0))
            if _is_centered(img.bbox, page_width, page_height):
                score += CENTERED_WEIGHT
                reasons.append("roughly centered on the page")

            if score <= 0:
                continue

            candidates.append(
                WatermarkCandidate(
                    candidate_id=str(uuid.uuid4()),
                    type="image",
                    text=f"Image ({img.width}\u00d7{img.height})",
                    page=img.page,
                    bbox=img.bbox,
                    rotation_degrees=0.0,
                    confidence=round(min(score, 1.0), 2),
                    reasons=reasons,
                    xref=xref,
                )
            )

    return candidates


def generate_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
    candidates = _generate_text_candidates(analysis) + _generate_image_candidates(analysis)
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates
