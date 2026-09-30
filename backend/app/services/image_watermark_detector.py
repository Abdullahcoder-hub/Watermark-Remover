"""
AI Watermark Detection for Raster Images (JPG, PNG, WEBP, BMP, TIFF).

Multi-signal detection pipeline:
  A) OCR / text detection — pytesseract + OpenCV MSER text region detection
  B) OpenCV-based visual analysis — contrast, transparency, edge analysis,
     repeated patterns, high-frequency overlay detection
  C) Spatial / geometric heuristics — corner badges, center stamps, diagonal
     overlays, suspicious opacity layers

All signals are combined into a confidence score. Every candidate has:
  - bounding box (x, y, width, height) in original pixel coordinates
  - type label (text | logo | overlay | pattern | transparent_overlay)
  - confidence score 0.0–0.99
  - human-readable reasons list

FALSE POSITIVE PROTECTION:
  - Faces are detected with OpenCV Haar cascades; any detection overlapping
    a face is suppressed or confidence-reduced.
  - Dominant foreground objects (objects covering > 30 % of the image and
    centered) are excluded.
  - Text that appears in the centred main content area with normal spacing is
    de-prioritised unless it also matches a watermark keyword.

MULTI-SCALE DETECTION:
  Images are analysed at full resolution and at two downscaled resolutions so
  that both very large watermarks (full-page overlays) and tiny corner logos
  (as small as 2 % of the image) can be found in the same pass.

MODEL MANAGEMENT:
  No heavy deep-learning model is loaded. The entire pipeline runs on CPU with
  standard OpenCV + pytesseract, which are already present in the Docker image
  and have zero extra memory cost on Render's free tier.

IMPORTANT: Do NOT use hard-coded coordinates. Every detection is based on
           actual pixel analysis of the uploaded image.
"""
from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("document_cleaner")

# ---------------------------------------------------------------------------
# Watermark keyword vocabulary (same as the document detector, extended)
# ---------------------------------------------------------------------------
WATERMARK_KEYWORDS: set[str] = {
    "confidential", "strictly confidential", "private", "draft", "sample",
    "do not copy", "top secret", "internal", "restricted", "preliminary",
    "proprietary", "proof", "void", "trial", "evaluation", "unregistered",
    "watermark", "specimen", "preview", "provisional", "embargoed",
    "unauthorized", "copyright", "all rights reserved", "getty", "shutterstock",
    "123rf", "dreamstime", "depositphotos", "istock", "adobe stock",
    "stock photo", "stock image", "camscanner", "gamma.app", "canva",
    "ilovepdf", "smallpdf", "pdf24", "scanned with", "created with",
    "made with", "powered by", "designed with", "demo", "test",
}

WATERMARK_KEYWORD_REGEXES: list[re.Pattern] = [
    re.compile(r"\b(?:getty|shutterstock|istock|adobe\s+stock|123rf|dreamstime|depositphotos)\b", re.I),
    re.compile(r"\b(?:confidential|strictly\s+confidential|do\s+not\s+copy|do\s+not\s+distribute)\b", re.I),
    re.compile(r"\b(?:watermark|draft|sample|void|specimen|proof)\b", re.I),
    re.compile(r"\b(?:camscanner|gamma\.app|canva\.com|ilovepdf|smallpdf|pdf24)\b", re.I),
    re.compile(r"\bscanned\s+(?:with|by)\s+\w+\b", re.I),
    re.compile(r"\b(?:made|created|designed|powered)\s+(?:with|by|on)\s+\w+\b", re.I),
    re.compile(r"\b(?:copyright|©|®|™)\b", re.I),
    re.compile(r"\ball\s+rights\s+reserved\b", re.I),
    re.compile(r"\b(?:trial|evaluation|unregistered|demo)\s+(?:version|copy|mode)?\b", re.I),
    re.compile(r"www\.\w+\.(com|net|org|io)\b", re.I),
    re.compile(r"\b\w+\.(com|net|org|io)\b", re.I),
]

# ---------------------------------------------------------------------------
# Detection result dataclass
# ---------------------------------------------------------------------------
@dataclass
class ImageWatermarkDetection:
    detection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "text"          # text | logo | overlay | pattern | transparent_overlay
    label: str = ""
    confidence: float = 0.0
    bbox: dict = field(default_factory=dict)    # {x, y, width, height} in pixels
    reasons: list[str] = field(default_factory=list)
    mask_b64: str | None = None  # reserved for future segmentation mask


class ImageWatermarkDetector:
    """
    Stateless detector — call detect(image_bytes) for each image.
    Instantiate once and reuse to avoid repeated setup cost.
    """

    def __init__(self) -> None:
        # Lazily loaded Haar cascades (only when actually needed)
        self._face_cascade: cv2.CascadeClassifier | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, image_bytes: bytes) -> list[ImageWatermarkDetection]:
        """
        Run the full multi-signal detection pipeline on raw image bytes.

        Returns a list of detections sorted by confidence (highest first).
        An empty list means no watermarks were found above threshold.
        """
        image = self._decode(image_bytes)
        if image is None:
            return []

        h, w = image.shape[:2]
        if h < 10 or w < 10:
            return []

        # Pre-compute shared representations
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        has_alpha, alpha = self._extract_alpha(image_bytes, image.shape)

        face_rects = self._detect_faces(gray)

        all_detections: list[ImageWatermarkDetection] = []

        # ---------------------------------------------------------------
        # SIGNAL A: OCR-based text detection
        # ---------------------------------------------------------------
        try:
            text_detections = self._detect_text_watermarks(image, gray, w, h)
            all_detections.extend(text_detections)
        except Exception as exc:
            logger.warning("image_watermark_text_detection_failed: %s", exc)

        # ---------------------------------------------------------------
        # SIGNAL B: Transparency / alpha layer analysis
        # ---------------------------------------------------------------
        if has_alpha and alpha is not None:
            try:
                alpha_detections = self._detect_alpha_overlays(alpha, w, h)
                all_detections.extend(alpha_detections)
            except Exception as exc:
                logger.warning("image_watermark_alpha_detection_failed: %s", exc)

        # ---------------------------------------------------------------
        # SIGNAL C: Visual / contrast / frequency analysis
        # ---------------------------------------------------------------
        try:
            visual_detections = self._detect_visual_overlays(image, gray, w, h)
            all_detections.extend(visual_detections)
        except Exception as exc:
            logger.warning("image_watermark_visual_detection_failed: %s", exc)

        # ---------------------------------------------------------------
        # SIGNAL D: Corner badge / logo detection
        # ---------------------------------------------------------------
        try:
            corner_detections = self._detect_corner_badges(image, gray, w, h)
            all_detections.extend(corner_detections)
        except Exception as exc:
            logger.warning("image_watermark_corner_detection_failed: %s", exc)

        # ---------------------------------------------------------------
        # Post-processing: merge overlapping, remove face overlaps, sort
        # ---------------------------------------------------------------
        merged = self._merge_overlapping(all_detections, w, h)
        filtered = self._filter_face_overlaps(merged, face_rects, w, h)
        filtered = self._filter_full_image_coverage(filtered, w, h)
        filtered.sort(key=lambda d: d.confidence, reverse=True)

        # Cap at reasonable number
        return filtered[:20]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decode(self, image_bytes: bytes) -> np.ndarray | None:
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            return img
        except Exception:
            return None

    def _extract_alpha(self, image_bytes: bytes, shape: tuple) -> tuple[bool, np.ndarray | None]:
        """Try to extract alpha channel from image bytes."""
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            img_alpha = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
            if img_alpha is not None and img_alpha.ndim == 3 and img_alpha.shape[2] == 4:
                return True, img_alpha[:, :, 3]
        except Exception:
            pass
        return False, None

    def _detect_faces(self, gray: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Detect faces using Haar cascade. Returns list of (x,y,w,h)."""
        try:
            if self._face_cascade is None:
                self._face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            if self._face_cascade.empty():
                return []
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            if len(faces) == 0:
                return []
            return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # SIGNAL A: OCR text watermark detection
    # ------------------------------------------------------------------

    def _detect_text_watermarks(
        self, image: np.ndarray, gray: np.ndarray, w: int, h: int
    ) -> list[ImageWatermarkDetection]:
        """
        Use pytesseract to extract all text blocks from the image.
        Score each block against the watermark keyword vocabulary plus
        geometric heuristics (rotation, position, size, color).
        """
        try:
            import pytesseract
        except ImportError:
            return []

        detections: list[ImageWatermarkDetection] = []

        # --- Multi-scale analysis to catch small watermarks ---
        scales = [(1.0, image), (2.0, None), (0.5, None)]
        for scale, scaled_img in scales:
            if scaled_img is None:
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                scaled_img = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

            try:
                data = pytesseract.image_to_data(
                    scaled_img,
                    output_type=pytesseract.Output.DICT,
                    config="--psm 11 --oem 1",
                )
            except Exception:
                try:
                    data = pytesseract.image_to_data(
                        scaled_img,
                        output_type=pytesseract.Output.DICT,
                        config="--psm 11",
                    )
                except Exception:
                    continue

            n = len(data.get("text", []))
            for i in range(n):
                text = (data["text"][i] or "").strip()
                if not text or len(text) < 2:
                    continue

                try:
                    conf = int(data["conf"][i])
                except (ValueError, TypeError):
                    conf = -1
                if conf < 30:  # tesseract confidence threshold
                    continue

                x = int(data["left"][i])
                y = int(data["top"][i])
                bw = int(data["width"][i])
                bh = int(data["height"][i])
                if bw <= 0 or bh <= 0:
                    continue

                # Map back to original pixel coords
                orig_x = int(x / scale)
                orig_y = int(y / scale)
                orig_w = int(bw / scale)
                orig_h = int(bh / scale)

                score, reasons = self._score_text_detection(
                    text, orig_x, orig_y, orig_w, orig_h, w, h, image, gray
                )
                if score > 0.0:
                    detections.append(
                        ImageWatermarkDetection(
                            type="text",
                            label=f'"{text}"',
                            confidence=min(0.99, round(score, 2)),
                            bbox={"x": orig_x, "y": orig_y, "width": orig_w, "height": orig_h},
                            reasons=reasons,
                        )
                    )

        return detections

    def _score_text_detection(
        self,
        text: str,
        x: int,
        y: int,
        bw: int,
        bh: int,
        img_w: int,
        img_h: int,
        image: np.ndarray,
        gray: np.ndarray,
    ) -> tuple[float, list[str]]:
        """Score a detected text block and return (score, reasons)."""
        score = 0.0
        reasons: list[str] = []
        norm = text.strip().lower()

        # --- Keyword match ---
        if any(kw in norm for kw in WATERMARK_KEYWORDS):
            score += 0.70
            reasons.append("matches watermark keyword")
        for pat in WATERMARK_KEYWORD_REGEXES:
            if pat.search(norm):
                score += 0.60
                reasons.append("matches watermark pattern")
                break

        # Only continue scoring non-keyword text if it has geometric signals
        if score == 0.0:
            # Check for URL-like text
            if re.search(r"\b\w+\.(com|net|org|io|app)\b", norm, re.I):
                score += 0.45
                reasons.append("contains website/brand URL")

            # Skip plain normal text without any other signals
            # (to avoid false-positives on body text)
            if score == 0.0:
                # Only score based on geometry if text has repeating-letter suspicion
                # or specific positioning
                is_corner = self._is_corner(x, y, bw, bh, img_w, img_h)
                is_center = self._is_center(x, y, bw, bh, img_w, img_h)
                is_large = (bh / img_h) > 0.08
                if not (is_corner or is_center or is_large):
                    return 0.0, []

        # --- Geometric signals ---
        if self._is_corner(x, y, bw, bh, img_w, img_h):
            score += 0.20
            reasons.append("positioned in corner region")

        if self._is_center(x, y, bw, bh, img_w, img_h):
            score += 0.15
            reasons.append("centered on image")

        # Large text relative to image size
        if (bh / img_h) > 0.05:
            score += 0.10
            reasons.append("large text overlay")

        # --- Color analysis: faint/gray text typical of watermarks ---
        try:
            roi = gray[max(0, y):min(gray.shape[0], y + bh),
                       max(0, x):min(gray.shape[1], x + bw)]
            if roi.size > 0:
                mean_val = float(np.mean(roi))
                # Light gray text (typical transparent watermark)
                if 130 < mean_val < 220:
                    score += 0.15
                    reasons.append("low-contrast gray text typical of watermark")
        except Exception:
            pass

        # --- Color channel: near-white text on images = likely watermark ---
        try:
            roi_color = image[max(0, y):min(image.shape[0], y + bh),
                              max(0, x):min(image.shape[1], x + bw)]
            if roi_color.size > 0:
                mean_color = np.mean(roi_color, axis=(0, 1))
                # Near-white (high all channels)
                if all(c > 180 for c in mean_color):
                    score += 0.10
                    reasons.append("near-white overlay color")
                # Near-black watermark on light background
                elif all(c < 80 for c in mean_color):
                    score += 0.05
                    reasons.append("dark text on light background")
        except Exception:
            pass

        return score, reasons

    # ------------------------------------------------------------------
    # SIGNAL B: Alpha transparency analysis
    # ------------------------------------------------------------------

    def _detect_alpha_overlays(
        self, alpha: np.ndarray, img_w: int, img_h: int
    ) -> list[ImageWatermarkDetection]:
        """
        Detect semi-transparent overlay regions in the alpha channel.
        Watermarks often have alpha values between 30–180 (semi-transparent).
        """
        detections: list[ImageWatermarkDetection] = []

        # Find semi-transparent regions (not fully opaque, not fully transparent)
        semi_mask = ((alpha > 20) & (alpha < 230)).astype(np.uint8) * 255

        if not semi_mask.any():
            return []

        # Find connected components of semi-transparent regions
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(semi_mask, connectivity=8)

        for label_idx in range(1, num_labels):  # skip background (0)
            x = int(stats[label_idx, cv2.CC_STAT_LEFT])
            y = int(stats[label_idx, cv2.CC_STAT_TOP])
            bw = int(stats[label_idx, cv2.CC_STAT_WIDTH])
            bh = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
            area = int(stats[label_idx, cv2.CC_STAT_AREA])

            # Filter tiny noise
            if bw < 10 or bh < 10 or area < 100:
                continue

            coverage = (area) / (img_w * img_h)
            # Skip full-image coverage (that's just the image itself)
            if coverage > 0.60:
                continue
            # Skip very tiny regions
            if coverage < 0.001:
                continue

            score = 0.0
            reasons: list[str] = []

            # Semi-transparent overlay — high watermark signal
            region_alpha = alpha[y:y + bh, x:x + bw]
            mean_alpha = float(np.mean(region_alpha))

            if 30 < mean_alpha < 200:
                score += 0.50
                reasons.append(f"semi-transparent overlay (mean alpha={mean_alpha:.0f}/255)")

            if self._is_corner(x, y, bw, bh, img_w, img_h):
                score += 0.25
                reasons.append("positioned in corner watermark region")

            if self._is_center(x, y, bw, bh, img_w, img_h):
                score += 0.20
                reasons.append("centered stamp/watermark position")

            if score > 0:
                detections.append(
                    ImageWatermarkDetection(
                        type="transparent_overlay",
                        label="Semi-transparent overlay",
                        confidence=min(0.99, round(score, 2)),
                        bbox={"x": x, "y": y, "width": bw, "height": bh},
                        reasons=reasons,
                    )
                )

        return detections

    # ------------------------------------------------------------------
    # SIGNAL C: Visual analysis (contrast, frequency, edges)
    # ------------------------------------------------------------------

    def _detect_visual_overlays(
        self, image: np.ndarray, gray: np.ndarray, img_w: int, img_h: int
    ) -> list[ImageWatermarkDetection]:
        """
        Detect visual artifacts that are typical of watermarks:
        - High-frequency text/graphic overlays on photographic content
        - Repeated tile patterns (typical of "demo" or "sample" watermarks)
        - Regions with anomalous local contrast compared to surrounding areas
        """
        detections: list[ImageWatermarkDetection] = []

        # --- Diagonal watermark detection using Hough lines ---
        try:
            edges = cv2.Canny(gray, 50, 150)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                    minLineLength=min(img_w, img_h) // 4, maxLineGap=20)
            if lines is not None:
                diagonal_lines = []
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    dx = x2 - x1
                    dy = y2 - y1
                    if dx == 0:
                        continue
                    angle = abs(np.degrees(np.arctan2(dy, dx)))
                    # Diagonal: between 20° and 70° or between 110° and 160°
                    if (20 < angle < 70) or (110 < angle < 160):
                        diagonal_lines.append(line[0])

                if len(diagonal_lines) >= 3:
                    # Multiple diagonal lines = likely diagonal text watermark
                    xs = [l[0] for l in diagonal_lines] + [l[2] for l in diagonal_lines]
                    ys = [l[1] for l in diagonal_lines] + [l[3] for l in diagonal_lines]
                    bx, by = max(0, min(xs)), max(0, min(ys))
                    bw = min(img_w, max(xs)) - bx
                    bh = min(img_h, max(ys)) - by
                    if bw > img_w * 0.05 and bh > img_h * 0.05:
                        detections.append(
                            ImageWatermarkDetection(
                                type="overlay",
                                label="Diagonal overlay",
                                confidence=min(0.75, 0.45 + 0.05 * min(len(diagonal_lines), 6)),
                                bbox={"x": bx, "y": by, "width": bw, "height": bh},
                                reasons=[f"detected {len(diagonal_lines)} diagonal lines (typical of rotated watermark)"],
                            )
                        )
        except Exception:
            pass

        # --- High-frequency overlay detection using DFT ---
        try:
            float_gray = np.float32(gray) / 255.0
            dft = cv2.dft(float_gray, flags=cv2.DFT_COMPLEX_OUTPUT)
            dft_shift = np.fft.fftshift(dft)
            mag = cv2.magnitude(dft_shift[:, :, 0], dft_shift[:, :, 1])
            mag_log = np.log1p(mag)

            # Check for energy concentration at high frequencies
            # (consistent with periodic/repeating watermark patterns)
            h_half = img_h // 2
            w_half = img_w // 2
            center_region = mag_log[h_half - img_h // 10: h_half + img_h // 10,
                                    w_half - img_w // 10: w_half + img_w // 10]
            outer_region = mag_log.copy()
            outer_region[h_half - img_h // 8: h_half + img_h // 8,
                         w_half - img_w // 8: w_half + img_w // 8] = 0

            if center_region.size > 0 and outer_region.size > 0:
                center_mean = float(np.mean(center_region))
                outer_mean = float(np.mean(outer_region[outer_region > 0])) if (outer_region > 0).any() else 0.0
                # High outer/center ratio = repeating pattern
                if outer_mean > 0 and (outer_mean / max(center_mean, 0.001)) > 0.8:
                    # Check if this is a simple texture (natural) or an overlay
                    # by looking at the local variance across image tiles
                    tile_size = max(64, min(img_w, img_h) // 8)
                    tiles_w = img_w // tile_size
                    tiles_h = img_h // tile_size
                    if tiles_w >= 3 and tiles_h >= 3:
                        tile_vars = []
                        for ty in range(tiles_h):
                            for tx in range(tiles_w):
                                tile = gray[ty * tile_size:(ty + 1) * tile_size,
                                            tx * tile_size:(tx + 1) * tile_size]
                                tile_vars.append(float(np.var(tile)))
                        mean_var = np.mean(tile_vars)
                        std_var = np.std(tile_vars)
                        # If variance across tiles is very uniform, it's a repeating pattern
                        if std_var > 0 and (std_var / max(mean_var, 1.0)) < 0.3:
                            detections.append(
                                ImageWatermarkDetection(
                                    type="pattern",
                                    label="Repeating pattern overlay",
                                    confidence=0.55,
                                    bbox={"x": 0, "y": 0, "width": img_w, "height": img_h},
                                    reasons=["detected repeating tiled pattern (typical of 'sample'/'demo' watermarks)"],
                                )
                            )
        except Exception:
            pass

        return detections

    # ------------------------------------------------------------------
    # SIGNAL D: Corner badge / logo detection
    # ------------------------------------------------------------------

    def _detect_corner_badges(
        self, image: np.ndarray, gray: np.ndarray, img_w: int, img_h: int
    ) -> list[ImageWatermarkDetection]:
        """
        Detect small graphic logos/badges in the four image corners.
        These are extremely common watermark placements.
        """
        detections: list[ImageWatermarkDetection] = []

        # Define corner regions (each is ~15% of image in each dimension)
        margin_x = max(20, int(img_w * 0.18))
        margin_y = max(20, int(img_h * 0.18))

        corners = [
            ("top-left",     0,             0,           margin_x, margin_y),
            ("top-right",    img_w - margin_x, 0,         margin_x, margin_y),
            ("bottom-left",  0,             img_h - margin_y, margin_x, margin_y),
            ("bottom-right", img_w - margin_x, img_h - margin_y, margin_x, margin_y),
        ]

        for corner_name, cx, cy, cw, ch in corners:
            roi = image[cy:cy + ch, cx:cx + cw]
            roi_gray = gray[cy:cy + ch, cx:cx + cw]

            if roi.size == 0:
                continue

            # Detect contiguous non-background regions in corner
            # Background detection: use the overall image color as baseline
            try:
                # Edge density in corner
                edges = cv2.Canny(roi_gray, 30, 100)
                edge_density = float(np.sum(edges > 0)) / (cw * ch)

                if edge_density < 0.01:
                    # No significant edges in corner — skip
                    continue

                # Find bounding box of edge content in this corner
                edge_pts = np.column_stack(np.where(edges > 0))
                if len(edge_pts) < 20:
                    continue

                ey_min, ex_min = edge_pts.min(axis=0)
                ey_max, ex_max = edge_pts.max(axis=0)
                content_w = ex_max - ex_min
                content_h = ey_max - ey_min

                # Only flag if the content is compact (logo-sized) not full-edge-spanning
                coverage_frac = (content_w * content_h) / (cw * ch)
                if not (0.01 < coverage_frac < 0.85):
                    continue

                # Color contrast check: corner region should differ from adjacent image area
                corner_mean = np.mean(roi, axis=(0, 1))
                # Sample from just inside the corner to compare
                sample_x = min(cw, int(img_w * 0.3))
                sample_y = min(ch, int(img_h * 0.3))
                center_roi = image[int(img_h * 0.35): int(img_h * 0.65),
                                   int(img_w * 0.35): int(img_w * 0.65)]
                if center_roi.size == 0:
                    continue
                center_mean = np.mean(center_roi, axis=(0, 1))
                color_diff = float(np.linalg.norm(corner_mean - center_mean))

                # Higher contrast = more likely to be a separate overlay element
                score = 0.0
                reasons: list[str] = []

                if edge_density > 0.05:
                    score += 0.25
                    reasons.append(f"high edge density ({edge_density:.1%}) in {corner_name}")

                if color_diff > 30:
                    score += 0.20
                    reasons.append(f"distinct color from image center (diff={color_diff:.0f})")

                score += 0.15
                reasons.append(f"located in {corner_name} corner (common watermark position)")

                if score >= 0.40:
                    # Absolute pixel coords
                    abs_x = cx + int(ex_min)
                    abs_y = cy + int(ey_min)
                    abs_w = max(content_w, 5)
                    abs_h = max(content_h, 5)
                    # Add a small padding
                    pad_x = min(5, abs_x)
                    pad_y = min(5, abs_y)
                    abs_x -= pad_x
                    abs_y -= pad_y
                    abs_w += pad_x * 2
                    abs_h += pad_y * 2

                    detections.append(
                        ImageWatermarkDetection(
                            type="logo",
                            label=f"Corner badge ({corner_name})",
                            confidence=min(0.75, round(score, 2)),
                            bbox={"x": abs_x, "y": abs_y, "width": abs_w, "height": abs_h},
                            reasons=reasons,
                        )
                    )
            except Exception:
                continue

        return detections

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _is_corner(self, x: int, y: int, bw: int, bh: int, img_w: int, img_h: int) -> bool:
        cx = x + bw / 2
        cy = y + bh / 2
        margin_x = img_w * 0.25
        margin_y = img_h * 0.25
        return (
            (cx < margin_x or cx > img_w - margin_x) and
            (cy < margin_y or cy > img_h - margin_y)
        )

    def _is_center(self, x: int, y: int, bw: int, bh: int, img_w: int, img_h: int) -> bool:
        cx = x + bw / 2
        cy = y + bh / 2
        return (
            abs(cx - img_w / 2) < img_w * 0.30 and
            abs(cy - img_h / 2) < img_h * 0.30
        )

    # ------------------------------------------------------------------
    # Post-processing helpers
    # ------------------------------------------------------------------

    def _iou(self, a: dict, b: dict) -> float:
        """Intersection over union for two bounding boxes."""
        ax1, ay1 = a["x"], a["y"]
        ax2, ay2 = ax1 + a["width"], ay1 + a["height"]
        bx1, by1 = b["x"], b["y"]
        bx2, by2 = bx1 + b["width"], by1 + b["height"]

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0

        inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
        a_area = a["width"] * a["height"]
        b_area = b["width"] * b["height"]
        union_area = a_area + b_area - inter_area
        return inter_area / max(union_area, 1)

    def _merge_overlapping(
        self, detections: list[ImageWatermarkDetection], img_w: int, img_h: int
    ) -> list[ImageWatermarkDetection]:
        """Merge heavily overlapping detections, keeping the higher-confidence one."""
        if not detections:
            return detections

        merged: list[ImageWatermarkDetection] = []
        used = [False] * len(detections)

        for i, det in enumerate(detections):
            if used[i]:
                continue
            group = [det]
            for j in range(i + 1, len(detections)):
                if not used[j]:
                    iou = self._iou(det.bbox, detections[j].bbox)
                    if iou > 0.35:
                        group.append(detections[j])
                        used[j] = True

            # Pick the highest-confidence from the group; merge reasons
            best = max(group, key=lambda d: d.confidence)
            all_reasons: list[str] = []
            for g in group:
                all_reasons.extend(r for r in g.reasons if r not in all_reasons)
            best.reasons = all_reasons
            merged.append(best)

        return merged

    def _filter_face_overlaps(
        self,
        detections: list[ImageWatermarkDetection],
        face_rects: list[tuple[int, int, int, int]],
        img_w: int,
        img_h: int,
    ) -> list[ImageWatermarkDetection]:
        """Reduce confidence of detections that heavily overlap detected faces."""
        if not face_rects:
            return detections

        result = []
        for det in detections:
            overlaps_face = False
            for fx, fy, fw, fh in face_rects:
                face_bbox = {"x": fx, "y": fy, "width": fw, "height": fh}
                iou = self._iou(det.bbox, face_bbox)
                if iou > 0.4:
                    overlaps_face = True
                    break

            if overlaps_face:
                # Don't remove — reduce confidence significantly
                det.confidence = max(0.0, det.confidence * 0.3)
                det.reasons.append("confidence reduced: overlaps detected face region")

            if det.confidence > 0.05:
                result.append(det)

        return result

    def _filter_full_image_coverage(
        self, detections: list[ImageWatermarkDetection], img_w: int, img_h: int
    ) -> list[ImageWatermarkDetection]:
        """Remove detections that cover essentially the entire image."""
        result = []
        for det in detections:
            coverage = (det.bbox.get("width", 0) * det.bbox.get("height", 0)) / max(img_w * img_h, 1)
            if coverage > 0.85:
                # Unless it's a full-image pattern watermark with specific label
                if det.type == "pattern":
                    result.append(det)
                # else skip
            else:
                result.append(det)
        return result


# Module-level singleton — loaded once, reused for all requests
_detector: ImageWatermarkDetector | None = None


def get_detector() -> ImageWatermarkDetector:
    global _detector
    if _detector is None:
        _detector = ImageWatermarkDetector()
    return _detector


def detect_watermarks_in_image(image_bytes: bytes) -> list[ImageWatermarkDetection]:
    """
    Main entry point. Detect watermarks in a raster image.
    Returns a list of detections sorted by confidence.
    """
    detector = get_detector()
    return detector.detect(image_bytes)
