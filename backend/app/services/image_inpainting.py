"""
Enhanced inpainting and smart pixel-level mask generation for images and video frames.
Avoids rectangular patches by extracting watermark/text/logo strokes within bounding boxes.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
import cv2
import numpy as np

logger = logging.getLogger("document_cleaner")

BASE_INPAINT_RADIUS = 5
MAX_INPAINT_RADIUS = 15


class ImageInpaintingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def build_smart_mask(
    image: np.ndarray,
    bboxes: list[dict],
    refine_strokes: bool = True,
) -> np.ndarray:
    """
    Generate pixel-level mask with adaptive dilation for watermark removal.
    If refine_strokes=True, segments watermark characters/graphics to avoid removing background.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mask = np.zeros((h, w), dtype=np.uint8)

    for bbox in bboxes:
        x = max(0, int(bbox.get("x", 0)))
        y = max(0, int(bbox.get("y", 0)))
        bw = max(1, min(w - x, int(bbox.get("width", 0))))
        bh = max(1, min(h - y, int(bbox.get("height", 0))))
        if bw <= 0 or bh <= 0:
            continue

        roi_gray = gray[y:y + bh, x:x + bw]
        if roi_gray.size == 0:
            continue

        area_frac = (bw * bh) / max(w * h, 1)
        dilation = 3 if area_frac > 0.05 else (5 if area_frac > 0.01 else 7)

        if refine_strokes and bw > 8 and bh > 8 and area_frac < 0.35:
            # Estimate background from outer edges of ROI
            top_b = roi_gray[0, :]
            bot_b = roi_gray[-1, :]
            left_b = roi_gray[:, 0]
            right_b = roi_gray[:, -1]
            border_vals = np.concatenate([top_b, bot_b, left_b, right_b])
            bg_median = np.median(border_vals)

            diff = cv2.absdiff(roi_gray, int(bg_median))
            _, stroke = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Fallback if threshold is too noisy or empty
            stroke_ratio = np.sum(stroke > 0) / float(bw * bh)
            if 0.04 < stroke_ratio < 0.85:
                k_size = max(2, min(5, dilation // 2))
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_size, k_size))
                stroke = cv2.dilate(stroke, kernel, iterations=1)
                mask[y:y + bh, x:x + bw] = np.maximum(mask[y:y + bh, x:x + bw], stroke)
                continue

        # Fallback to padded bounding box
        pad = max(2, dilation)
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w, x + bw + pad), min(h, y + bh + pad)
        mask[y0:y1, x0:x1] = 255

    return mask


def inpaint_frame(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Inpaint a single image frame using Telea with Navier-Stokes fallback."""
    if not mask.any():
        return image
    h, w = image.shape[:2]
    masked_frac = np.sum(mask > 0) / float(w * h)
    inpaint_radius = MAX_INPAINT_RADIUS if masked_frac > 0.1 else (8 if masked_frac > 0.03 else BASE_INPAINT_RADIUS)

    try:
        return cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)
    except Exception:
        return cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_NS)


def remove_watermarks_from_image(
    image_bytes: bytes,
    bboxes: list[dict],
    original_filename: str = "image.jpg",
) -> bytes:
    if not bboxes:
        raise ImageInpaintingError("NO_REGIONS", "No regions were specified for removal.")

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageInpaintingError("DECODE_FAILED", "The image could not be decoded.")

    mask = build_smart_mask(image, bboxes, refine_strokes=True)
    if not mask.any():
        raise ImageInpaintingError("EMPTY_MASK", "The removal mask is empty.")

    result = inpaint_frame(image, mask)

    ext = Path(original_filename).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 95])
    elif ext == ".png":
        ok, encoded = cv2.imencode(".png", result, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    elif ext == ".webp":
        ok, encoded = cv2.imencode(".webp", result, [cv2.IMWRITE_WEBP_QUALITY, 90])
    elif ext == ".bmp":
        ok, encoded = cv2.imencode(".bmp", result)
    elif ext in (".tiff", ".tif"):
        ok, encoded = cv2.imencode(".tiff", result)
    else:
        ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 95])

    if not ok or encoded is None:
        raise ImageInpaintingError("ENCODE_FAILED", "The cleaned image could not be encoded.")

    return encoded.tobytes()


def build_preview_with_detections(image_bytes: bytes, detections: list[dict]) -> bytes:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return image_bytes

    h, w = image.shape[:2]
    preview = image.copy()

    type_colors = {
        "text": (0, 165, 255),
        "logo": (0, 200, 100),
        "overlay": (200, 50, 255),
        "pattern": (50, 50, 255),
        "transparent_overlay": (255, 165, 0),
    }

    for det in detections:
        bbox = det.get("bbox", {})
        x = max(0, int(bbox.get("x", 0)))
        y = max(0, int(bbox.get("y", 0)))
        bw = int(bbox.get("width", 0))
        bh = int(bbox.get("height", 0))
        if bw <= 0 or bh <= 0:
            continue

        color = type_colors.get(det.get("type", "overlay"), (0, 165, 255))
        conf_pct = int(float(det.get("confidence", 0)) * 100)
        label_text = f"{det.get('label', 'Watermark')[:22]} ({conf_pct}%)"

        thickness = max(2, min(4, w // 300))
        cv2.rectangle(preview, (x, y), (x + bw, y + bh), color, thickness)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.4, min(0.65, w / 1200))
        (text_w, text_h), _ = cv2.getTextSize(label_text, font, font_scale, 1)

        label_y = y - 6 if y > text_h + 10 else y + bh + text_h + 6
        label_x = max(0, min(x, w - text_w - 4))
        cv2.rectangle(preview, (label_x - 2, label_y - text_h - 4), (label_x + text_w + 4, label_y + 4), color, -1)
        cv2.putText(preview, label_text, (label_x, label_y), font, font_scale, (255, 255, 255), 1, cv2.LINE_AA)

    ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return encoded.tobytes() if (ok and encoded is not None) else image_bytes
