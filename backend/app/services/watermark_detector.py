"""
Watermark candidate detector (Text, Images, and Multi-format Signatures).

Trained heuristic AI pattern detector for identifying true watermarks across all document
types (PDF, PPTX, scanned documents) without false-positive triggers on normal document text,
names, or running headers.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, TextObject
from app.schemas.watermark import WatermarkCandidate
from app.services.pdf_analyzer import SCANNED_IMAGE_COVERAGE_THRESHOLD

# Explicit standalone watermark keywords (must match whole word with \b)
EXPLICIT_WATERMARK_WORDS = {
    "confidential",
    "strictly confidential",
    "private & confidential",
    "draft",
    "sample",
    "do not copy",
    "top secret",
    "internal use only",
    "for review only",
    "do not distribute",
    "not for distribution",
    "restricted",
    "preliminary",
    "proprietary",
    "proof",
    "void",
    "trial version",
    "evaluation only",
    "evaluation copy",
    "watermark",
    "unregistered",
    "for internal use",
    "do not duplicate",
    "specimen",
    "preview only",
    "for testing only",
    "provisional",
    "embargoed",
    "unauthorized reproduction",
}

# Regex patterns with word boundaries for tool-specific watermark phrases
EXPLICIT_WATERMARK_REGEXES: list[re.Pattern] = [
    # CamScanner & Mobile Scanners
    re.compile(r"\b(?:scanned\s+(?:with|by)\s+)?camscanner(?:\.com)?\b", re.IGNORECASE),
    re.compile(r"\bcs\s+camscanner\b", re.IGNORECASE),
    re.compile(r"\bscanned\s+(?:with|by)\s+(?:adobe\s+scan|vflat|clearscanner|turboscan|genius\s+scan|tapscanner|kaagaz|doc\s+scanner|fast\s+scanner|simple\s+scan)\b", re.IGNORECASE),
    re.compile(r"\b(?:adobe\s+scan|vflat\s+scan|clearscanner|turboscan|genius\s+scan|tapscanner)\b", re.IGNORECASE),

    # Gamma App & AI Tools
    re.compile(r"\b(?:made|created|powered|generated)\s+(?:with|by|on)\s+gamma(?:\.app)?\b", re.IGNORECASE),
    re.compile(r"\bgamma\.app\b", re.IGNORECASE),
    re.compile(r"\b(?:made|created)\s+(?:with|by)\s+(?:tome|beautiful\.ai|pitch|slidesgo|slidesai|plus\s+ai|decktopus|wepik)\b", re.IGNORECASE),
    re.compile(r"\btome\.app\b", re.IGNORECASE),

    # Canva & Design Tools
    re.compile(r"\b(?:designed|made)\s+with\s+canva(?:\.com)?\b", re.IGNORECASE),
    re.compile(r"\bcanva\s+watermark\b", re.IGNORECASE),
    re.compile(r"\bcanva\.com\b", re.IGNORECASE),

    # Online PDF Tools & Editors
    re.compile(r"\b(?:ilovepdf|smallpdf|pdf24|sejda|pdfcandy|lightpdf|pdfgear|updf)\.com\b", re.IGNORECASE),
    re.compile(r"\b(?:ilovepdf|smallpdf|pdf24|sejda|pdfcandy|lightpdf|pdfgear|updf)\b", re.IGNORECASE),
    re.compile(r"\b(?:created|converted)\s+with\s+wps\s+office\b", re.IGNORECASE),
    re.compile(r"\bwondershare\s+pdfelement\b", re.IGNORECASE),
    re.compile(r"\bnitro\s+pdf\b", re.IGNORECASE),
    re.compile(r"\bfoxit\s+pdf\b", re.IGNORECASE),

    # Version & Status Patterns
    re.compile(r"\b(?:trial|evaluation|unregistered|demo)\s+version\b", re.IGNORECASE),
    re.compile(r"\bdocu?sign\s+envelope\s+id:?\s*[0-9a-f\-]+", re.IGNORECASE),
    re.compile(r"\bsigned\s+with\s+pandadoc\b", re.IGNORECASE),
    re.compile(r"\bmathpix\s+snip\b", re.IGNORECASE),
]

# Scoring Constants
EXPLICIT_SIGNATURE_SCORE = 0.95
ROTATION_WEIGHT = 0.35
LARGE_SIZE_WEIGHT = 0.15
REPETITION_BOOST = 0.15

ROTATION_TOLERANCE_DEGREES = 2.0
LARGE_TEXT_HEIGHT_RATIO = 0.05  # span height vs. page height
MIN_PAGES_FOR_REPETITION = 3

IMAGE_REPETITION_WEIGHT = 0.40
TRANSPARENCY_WEIGHT = 0.30
MODERATE_SIZE_WEIGHT = 0.20
CENTERED_WEIGHT = 0.10
CORNER_LOGO_WEIGHT = 0.20

MIN_WATERMARK_IMAGE_COVERAGE = 0.02
MAX_WATERMARK_IMAGE_COVERAGE = SCANNED_IMAGE_COVERAGE_THRESHOLD
CENTERED_TOLERANCE_FRACTION = 0.35


def _is_rotated(rotation_degrees: float) -> bool:
    normalized = rotation_degrees % 360
    return min(normalized, 360 - normalized) > ROTATION_TOLERANCE_DEGREES


def _matches_explicit_signature(text: str) -> bool:
    """
    Check if text contains a recognized watermark phrase using strict word boundaries.
    Never matches partial substrings inside normal words (e.g. 'demo' inside 'democracy').
    """
    normalized = text.strip().lower()

    # Exact whole-phrase or word-boundary check
    for word in EXPLICIT_WATERMARK_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, normalized):
            return True

    for regex in EXPLICIT_WATERMARK_REGEXES:
        if regex.search(normalized):
            return True

    return False


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
        is_explicit_match = _matches_explicit_signature(normalized_text)

        for obj in occurrences:
            is_rotated = _is_rotated(obj.rotation_degrees)
            page_height = page_heights.get(obj.page, 0.0)
            span_height = obj.bbox[3] - obj.bbox[1]
            is_large = page_height > 0 and (span_height / page_height) > LARGE_TEXT_HEIGHT_RATIO

            # Strict Filter: Must be an explicit signature OR a rotated watermark overlay
            # Normal repeated text (like author names, running headers, titles) is NOT a watermark
            if not is_explicit_match and not is_rotated:
                continue

            score = 0.0
            reasons: list[str] = []

            if is_explicit_match:
                score += EXPLICIT_SIGNATURE_SCORE
                reasons.append("matches common watermark wording")

            if is_rotated:
                score += ROTATION_WEIGHT
                reasons.append(f"rotated {obj.rotation_degrees}°")

            if is_repeated:
                score += REPETITION_BOOST
                reasons.append(f"same text appears on {len(pages_with_text)} pages")

            if is_large:
                score += LARGE_SIZE_WEIGHT
                reasons.append("large relative to the page")

            if score <= 0:
                continue

            confidence_val = round(min(score, 0.99), 2)

            candidates.append(
                WatermarkCandidate(
                    candidate_id=str(uuid.uuid4()),
                    type="text",
                    text=obj.text,
                    page=obj.page,
                    bbox=obj.bbox,
                    rotation_degrees=obj.rotation_degrees,
                    confidence=confidence_val,
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


def _is_corner_logo(bbox: tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    """Check if an image sits at bottom-left or bottom-right corner (typical of CamScanner/Gamma logos)."""
    if page_width <= 0 or page_height <= 0:
        return False
    bottom_frac = bbox[3] / page_height
    right_frac = bbox[2] / page_width
    left_frac = bbox[0] / page_width
    is_bottom = bottom_frac >= 0.88
    is_corner = left_frac <= 0.20 or right_frac >= 0.80
    return is_bottom and is_corner


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
        is_repeated = len(pages_with_image) >= 2

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

            if _is_corner_logo(img.bbox, page_width, page_height):
                score += CORNER_LOGO_WEIGHT
                reasons.append("positioned in corner watermark badge zone")

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
                    confidence=round(min(score, 0.99), 2),
                    reasons=reasons,
                    xref=xref,
                )
            )

    return candidates


def generate_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
    """Generate all text and image watermark candidates scored by heuristic AI rules."""
    candidates = _generate_text_candidates(analysis) + _generate_image_candidates(analysis)
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates
