"""
Watermark candidate detector (Text, Images, and Multi-format Signatures).

Trained heuristic AI pattern detector for identifying watermarks across all document
types (PDF, PPTX, scanned documents) without calling external cloud LLMs or using API tokens.

Detection Coverage:
  - Mobile Scanners: CamScanner, Adobe Scan, vFlat, ClearScanner, TurboScan, Genius Scan, Doc Scanner, TapScanner, Kaagaz.
  - AI & Slide Tools: Gamma ("Made with Gamma", "gamma.app"), Tome ("Made with Tome"), Beautiful.ai, Pitch, Prezi, Slidesgo, SlidesAI.
  - Graphic Design Tools: Canva ("Designed with Canva", "Made with Canva"), Figma.
  - PDF Utilities: iLovePDF, SmallPDF, PDF24, Sejda, Nitro, Foxit, Soda PDF, PDFcandy, Wondershare PDFelement, UPDF, WPS Office.
  - Document Stamps: CONFIDENTIAL, DRAFT, SAMPLE, COPY, DO NOT COPY, TOP SECRET, INTERNAL USE ONLY, FOR REVIEW ONLY,
    DO NOT DISTRIBUTE, RESTRICTED, PRELIMINARY, PROPRIETARY, PROOF, VOID, DEMO, TRIAL VERSION, EVALUATION ONLY, WATERMARK, UNREGISTERED.
  - E-Signatures: DocuSign ("DocuSign Envelope ID"), PandaDoc, Adobe Sign, SignNow, HelloSign.
  - Academic / Notes: Mathpix, Overleaf, Quizlet, Scribd, SlideShare, Course Hero.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, TextObject
from app.schemas.watermark import WatermarkCandidate
from app.services.pdf_analyzer import SCANNED_IMAGE_COVERAGE_THRESHOLD

# Explicit high-confidence watermark signatures (triggers >= 0.85 base confidence)
EXPLICIT_WATERMARK_SIGNATURES: set[str] = {
    # CamScanner & Mobile Scanners
    "camscanner",
    "scanned with camscanner",
    "scanned by camscanner",
    "cs camscanner",
    "camscanner.com",
    "cam scanner",
    "adobe scan",
    "scanned with adobe scan",
    "vflat",
    "scanned with vflat",
    "vflat scan",
    "clearscanner",
    "turboscan",
    "genius scan",
    "tapscanner",
    "kaagaz scanner",
    "simple scan",
    "doc scanner",
    "fast scanner",

    # Gamma App & AI Presentation Tools
    "made with gamma",
    "gamma.app",
    "created with gamma",
    "powered by gamma",
    "gamma app",
    "made on gamma",
    "made with tome",
    "tome.app",
    "beautiful.ai",
    "created with beautiful.ai",
    "pitch.com",
    "prezi",
    "slidesgo",
    "slidesai",
    "plus ai",
    "decktopus",
    "popai",
    "wepik",

    # Canva & Graphic Design
    "designed with canva",
    "made with canva",
    "canva watermark",
    "canva.com",
    "canva pro",

    # Online Converters & PDF Editors
    "ilovepdf",
    "smallpdf",
    "pdf24",
    "sejda",
    "nitro pdf",
    "foxit",
    "foxit pdf",
    "soda pdf",
    "pdfcandy",
    "easeus pdf",
    "wondershare pdfelement",
    "pdfelement",
    "updf",
    "pdfgear",
    "lightpdf",
    "wps office",
    "created with wps office",
    "kingsoft office",

    # Document Status & Security Stamps
    "confidential",
    "strictly confidential",
    "private & confidential",
    "draft",
    "sample",
    "copy",
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
    "demo",
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

    # E-Signatures & Verification
    "docusign",
    "docusign envelope id",
    "signed with pandadoc",
    "pandadoc",
    "adobe sign",
    "signnow",
    "hellosign",

    # Academic & Repositories
    "mathpix",
    "mathpix snip",
    "overleaf",
    "quizlet",
    "scribd",
    "slideshare",
    "course hero",
}

# Regex patterns for dynamic or phrased watermark text
WATERMARK_REGEX_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(?:scanned\s+(?:with|by))\s+[a-z0-9_\-\s]+", re.IGNORECASE),
    re.compile(r"\b(?:made|created|designed|powered)\s+(?:with|by|on)\s+(?:gamma|tome|canva|beautiful\.ai|slidesgo|pitch)", re.IGNORECASE),
    re.compile(r"\b(?:trial|evaluation|unregistered|demo)\s+version\b", re.IGNORECASE),
    re.compile(r"\bdocu?sign\s+envelope\s+id:?\s*[0-9a-f\-]+", re.IGNORECASE),
    re.compile(r"\b(?:gamma\.app|camscanner\.com|canva\.com|ilovepdf\.com|smallpdf\.com|pdf24\.org|sejda\.com)\b", re.IGNORECASE),
]

TEXT_REPETITION_WEIGHT = 0.40
ROTATION_WEIGHT = 0.30
EXPLICIT_KEYWORD_WEIGHT = 0.85
GENERAL_KEYWORD_WEIGHT = 0.20
SIZE_WEIGHT = 0.10
MARGIN_WEIGHT = 0.10

ROTATION_TOLERANCE_DEGREES = 1.0
LARGE_TEXT_HEIGHT_RATIO = 0.05  # span height vs. page height
MIN_PAGES_FOR_REPETITION = 2

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


def _matches_explicit_signature(normalized_text: str) -> bool:
    """Check if normalized text contains an explicit tool or status watermark."""
    if any(sig in normalized_text for sig in EXPLICIT_WATERMARK_SIGNATURES):
        return True
    return any(p.search(normalized_text) is not None for p in WATERMARK_REGEX_PATTERNS)


def _is_in_margin_zone(bbox: tuple[float, float, float, float], page_height: float) -> bool:
    """Check if text is placed in footer (>90% of height) or header (<8% of height) margin."""
    if page_height <= 0:
        return False
    top_fraction = bbox[1] / page_height
    bottom_fraction = bbox[3] / page_height
    return top_fraction < 0.08 or bottom_fraction > 0.90


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

            # Primary watermark signal check: must match keyword, be repeated, or be rotated
            if not (is_explicit_match or is_repeated or is_rotated):
                continue

            score = 0.0
            reasons: list[str] = []

            if is_repeated:
                score += TEXT_REPETITION_WEIGHT
                reasons.append(f"same text appears on {len(pages_with_text)} pages")

            if is_rotated:
                score += ROTATION_WEIGHT
                reasons.append(f"rotated {obj.rotation_degrees}°")

            if is_explicit_match:
                score += EXPLICIT_KEYWORD_WEIGHT
                reasons.append("matches common watermark wording")

            page_height = page_heights.get(obj.page, 0.0)
            span_height = obj.bbox[3] - obj.bbox[1]
            if page_height > 0 and (span_height / page_height) > LARGE_TEXT_HEIGHT_RATIO:
                score += SIZE_WEIGHT
                reasons.append("large relative to the page")

            if _is_in_margin_zone(obj.bbox, page_height) and is_explicit_match:
                score += MARGIN_WEIGHT

            if score <= 0:
                continue

            confidence_val = round(min(score, 1.0), 2)

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
                    confidence=round(min(score, 1.0), 2),
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
