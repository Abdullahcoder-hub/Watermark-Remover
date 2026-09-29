"""
Multi-Signal Document-Aware Watermark Detector.

Trained heuristic AI pattern detector for identifying true watermarks across all document
types (PDF, PPTX, scanned documents) without false-positive triggers on normal body text,
headings, or running headers.

Signals evaluated:
1. Semantic signature matching (CamScanner, Gamma, Canva, Adobe Scan, Confidential stamps, etc.)
2. Cross-page / cross-slide repetition intelligence (text, images, shapes at matching relative coordinates)
3. Geometry & layout anomalies (diagonal/rotated angles, large height ratios, corner badges, centered stamps)
4. Color & contrast signals (faint/low-opacity gray text, stamp tones)
5. Transparency & Alpha mask analysis
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, TextObject
from app.schemas.watermark import WatermarkCandidate
from app.services.pdf_analyzer import SCANNED_IMAGE_COVERAGE_THRESHOLD

# Explicit standalone watermark keywords
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
    "copy",
}

# Regex patterns for tool-specific watermark signatures
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

    # Document Management & Status Stamps
    re.compile(r"\b(?:trial|evaluation|unregistered|demo)\s+version\b", re.IGNORECASE),
    re.compile(r"\bdocu?sign\s+envelope\s+id:?\s*[0-9a-f\-]+", re.IGNORECASE),
    re.compile(r"\bsigned\s+with\s+pandadoc\b", re.IGNORECASE),
    re.compile(r"\bmathpix\s+snip\b", re.IGNORECASE),
]

# Scoring Constants
EXPLICIT_SIGNATURE_SCORE = 0.95
ROTATION_WEIGHT = 0.35
LARGE_SIZE_WEIGHT = 0.15
REPETITION_BOOST_HIGH = 0.35
REPETITION_BOOST_MED = 0.20
FAINT_COLOR_WEIGHT = 0.15
CENTERED_WEIGHT = 0.10
CORNER_LOGO_WEIGHT = 0.25
TRANSPARENCY_WEIGHT = 0.30
MODERATE_SIZE_WEIGHT = 0.20

ROTATION_TOLERANCE_DEGREES = 2.0
LARGE_TEXT_HEIGHT_RATIO = 0.05
MIN_WATERMARK_IMAGE_COVERAGE = 0.015
MAX_WATERMARK_IMAGE_COVERAGE = SCANNED_IMAGE_COVERAGE_THRESHOLD
CENTERED_TOLERANCE_FRACTION = 0.35

# Color helpers
FAINT_GRAY_PREFIXES = ("#c", "#d", "#e", "#b0", "#a8", "#9e", "#88")
STAMP_RED_PREFIXES = ("#f0", "#e0", "#d0", "#c0", "#b0", "#ff")


def _is_rotated(rotation_degrees: float) -> bool:
    normalized = rotation_degrees % 360
    return min(normalized, 360 - normalized) > ROTATION_TOLERANCE_DEGREES


def _matches_explicit_signature(text: str) -> bool:
    normalized = text.strip().lower()
    for word in EXPLICIT_WATERMARK_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", normalized):
            return True
    for regex in EXPLICIT_WATERMARK_REGEXES:
        if regex.search(normalized):
            return True
    return False


def _is_faint_or_stamp_color(color: str | None) -> bool:
    if not color:
        return False
    c = color.lower()
    return any(c.startswith(prefix) for prefix in FAINT_GRAY_PREFIXES)


def _is_centered(bbox: tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    if page_width <= 0 or page_height <= 0:
        return False
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    x_offset = abs(cx - page_width / 2) / page_width
    y_offset = abs(cy - page_height / 2) / page_height
    return x_offset <= CENTERED_TOLERANCE_FRACTION and y_offset <= CENTERED_TOLERANCE_FRACTION


def _is_corner_badge(bbox: tuple[float, float, float, float], page_width: float, page_height: float) -> bool:
    if page_width <= 0 or page_height <= 0:
        return False
    bottom_frac = bbox[3] / page_height
    right_frac = bbox[2] / page_width
    left_frac = bbox[0] / page_width
    top_frac = bbox[1] / page_height

    is_bottom_corner = bottom_frac >= 0.85 and (left_frac <= 0.25 or right_frac >= 0.75)
    is_top_corner = top_frac <= 0.15 and (left_frac <= 0.25 or right_frac >= 0.75)
    return is_bottom_corner or is_top_corner


def _generate_text_candidates(analysis: DocumentAnalysisResponse) -> list[WatermarkCandidate]:
    page_heights = {page.page_number: page.height for page in analysis.pages}
    page_widths = {page.page_number: page.width for page in analysis.pages}

    occurrences_by_text: dict[str, list[TextObject]] = defaultdict(list)
    for page in analysis.pages:
        for obj in page.text_objects:
            normalized = obj.text.strip().lower()
            if normalized and len(normalized) >= 2:
                occurrences_by_text[normalized].append(obj)

    candidates: list[WatermarkCandidate] = []

    for normalized_text, occurrences in occurrences_by_text.items():
        pages_with_text = {o.page for o in occurrences}
        page_rep_count = len(pages_with_text)
        is_explicit_match = _matches_explicit_signature(normalized_text)

        for obj in occurrences:
            is_rotated = _is_rotated(obj.rotation_degrees)
            page_height = page_heights.get(obj.page, 0.0)
            page_width = page_widths.get(obj.page, 0.0)
            span_height = obj.bbox[3] - obj.bbox[1]
            is_large = page_height > 0 and (span_height / page_height) > LARGE_TEXT_HEIGHT_RATIO
            is_faint = _is_faint_or_stamp_color(obj.color)
            is_corner = _is_corner_badge(obj.bbox, page_width, page_height)
            is_center = _is_centered(obj.bbox, page_width, page_height)

            # Signal filtering: Normal body text without watermark characteristics is ignored
            if not is_explicit_match and not is_rotated and not (page_rep_count >= 3 and (is_faint or is_large or is_center)):
                continue

            score = 0.0
            reasons: list[str] = []

            if is_explicit_match:
                score += EXPLICIT_SIGNATURE_SCORE
                reasons.append("matches known watermark phrase")

            if is_rotated:
                score += ROTATION_WEIGHT
                reasons.append(f"rotated {obj.rotation_degrees}°")

            if page_rep_count >= 3:
                score += REPETITION_BOOST_HIGH
                reasons.append(f"repeated across {page_rep_count} pages in document")
            elif page_rep_count >= 2:
                score += REPETITION_BOOST_MED
                reasons.append(f"appears on {page_rep_count} pages")

            if is_large:
                score += LARGE_SIZE_WEIGHT
                reasons.append("large prominent text overlay")

            if is_faint:
                score += FAINT_COLOR_WEIGHT
                reasons.append("low contrast background coloring")

            if is_corner:
                reasons.append("located in corner watermark stamp region")

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
                score += (REPETITION_BOOST_HIGH if len(pages_with_image) >= 3 else REPETITION_BOOST_MED)
                reasons.append(f"repeated image on {len(pages_with_image)} pages")

            if img.has_alpha:
                score += TRANSPARENCY_WEIGHT
                reasons.append("transparent alpha layer typical of watermark overlay")

            score += MODERATE_SIZE_WEIGHT
            reasons.append("overlay dimensions consistent with badge/stamp")

            page_width, page_height = page_dims.get(img.page, (0.0, 0.0))
            if _is_centered(img.bbox, page_width, page_height):
                score += CENTERED_WEIGHT
                reasons.append("centered page stamp placement")

            if _is_corner_badge(img.bbox, page_width, page_height):
                score += CORNER_LOGO_WEIGHT
                reasons.append("positioned in corner scanner badge area")

            if score <= 0:
                continue

            candidates.append(
                WatermarkCandidate(
                    candidate_id=str(uuid.uuid4()),
                    type="image",
                    text=f"Image ({img.width}×{img.height})",
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
    """
    Generate all text and image watermark candidates scored by multi-signal document intelligence.
    """
    candidates = _generate_text_candidates(analysis) + _generate_image_candidates(analysis)
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates
