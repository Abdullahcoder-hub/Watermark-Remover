"""
Image inpainting / watermark removal for raster images (JPG, PNG, WEBP, BMP, TIFF).

Uses OpenCV Telea inpainting (already installed — same as the scanned-PDF pipeline).
Also provides a NS (Navier-Stokes) fallback for large or complex regions.

The mask is built from the user-confirmed bounding boxes:
  - Each box is dilated slightly (adaptive to size) before inpainting so
    partial watermark pixels at the edges are also removed.
  - The dilation radius is adaptive: larger for small watermarks (where we want
    to be thorough) and smaller proportionally for large ones (where aggressive
    dilation would remove too much content).

Supported output formats: JPEG, PNG, WEBP.
The output format is preserved from the input format where possible.
Original image dimensions are always preserved.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("document_cleaner")

# Inpaint radius: starting point, adaptive adjustment applied per detection size
BASE_INPAINT_RADIUS = 5
MAX_INPAINT_RADIUS = 15


class ImageInpaintingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def remove_watermarks_from_image(
    image_bytes: bytes,
    bboxes: list[dict],           # list of {x, y, width, height} in pixels
    original_filename: str = "image.jpg",
) -> bytes:
    """
    Remove watermarks from a raster image using inpainting.

    Args:
        image_bytes: Raw bytes of the input image.
        bboxes: List of pixel-space bounding boxes to remove.
        original_filename: Used to determine output format.

    Returns:
        Raw bytes of the cleaned image in the same format as the input.

    Raises:
        ImageInpaintingError on failure.
    """
    if not bboxes:
        raise ImageInpaintingError("NO_REGIONS", "No regions were specified for removal.")

    # Decode
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageInpaintingError("DECODE_FAILED", "The image could not be decoded.")

    h, w = image.shape[:2]

    # Build mask
    mask = np.zeros((h, w), dtype=np.uint8)
    for bbox in bboxes:
        x = max(0, int(bbox.get("x", 0)))
        y = max(0, int(bbox.get("y", 0)))
        bw = int(bbox.get("width", 0))
        bh = int(bbox.get("height", 0))
        if bw <= 0 or bh <= 0:
            continue

        # Adaptive dilation
        region_area_frac = (bw * bh) / max(w * h, 1)
        if region_area_frac < 0.01:
            dilation = min(MAX_INPAINT_RADIUS, 12)  # small watermark: larger dilation
        elif region_area_frac < 0.05:
            dilation = 8
        else:
            dilation = BASE_INPAINT_RADIUS

        x0 = max(0, x - dilation)
        y0 = max(0, y - dilation)
        x1 = min(w, x + bw + dilation)
        y1 = min(h, y + bh + dilation)
        mask[y0:y1, x0:x1] = 255

    if not mask.any():
        raise ImageInpaintingError("EMPTY_MASK", "The removal mask is empty.")

    # Inpainting radius: adaptive
    total_masked = int(np.sum(mask > 0))
    image_area = w * h
    masked_frac = total_masked / max(image_area, 1)
    inpaint_radius = BASE_INPAINT_RADIUS
    if masked_frac > 0.10:
        inpaint_radius = MAX_INPAINT_RADIUS
    elif masked_frac > 0.05:
        inpaint_radius = 10

    # Primary method: Telea (fast, good for small watermarks)
    try:
        result = cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)
    except Exception as exc:
        logger.warning("telea_inpaint_failed, trying NS: %s", exc)
        try:
            result = cv2.inpaint(image, mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_NS)
        except Exception as exc2:
            raise ImageInpaintingError("INPAINT_FAILED", "Image inpainting failed.") from exc2

    # Encode back to the appropriate format
    ext = Path(original_filename).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 95])
        fmt = "jpg"
    elif ext == ".png":
        ok, encoded = cv2.imencode(".png", result, [cv2.IMWRITE_PNG_COMPRESSION, 6])
        fmt = "png"
    elif ext == ".webp":
        ok, encoded = cv2.imencode(".webp", result, [cv2.IMWRITE_WEBP_QUALITY, 90])
        fmt = "webp"
    elif ext == ".bmp":
        ok, encoded = cv2.imencode(".bmp", result)
        fmt = "bmp"
    elif ext in (".tiff", ".tif"):
        ok, encoded = cv2.imencode(".tiff", result)
        fmt = "tiff"
    else:
        # Default to JPEG
        ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, 95])
        fmt = "jpg"

    if not ok or encoded is None:
        raise ImageInpaintingError("ENCODE_FAILED", "The cleaned image could not be encoded.")

    return encoded.tobytes()


def build_preview_with_detections(
    image_bytes: bytes,
    detections: list[dict],  # list of {bbox: {x,y,width,height}, label, confidence, type, detection_id}
) -> bytes:
    """
    Overlay bounding boxes and labels onto the image for the detection preview.
    Returns JPEG bytes.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return image_bytes  # fallback: return original

    h, w = image.shape[:2]
    # Work on a copy
    preview = image.copy()

    # Color per detection type
    type_colors = {
        "text":               (0,   165, 255),  # orange
        "logo":               (0,   200, 100),  # green
        "overlay":            (200, 50,  255),  # purple
        "pattern":            (50,  50,  255),  # red
        "transparent_overlay":(255, 165, 0),    # blue
    }

    for det in detections:
        bbox = det.get("bbox", {})
        x = max(0, int(bbox.get("x", 0)))
        y = max(0, int(bbox.get("y", 0)))
        bw = int(bbox.get("width", 0))
        bh = int(bbox.get("height", 0))
        if bw <= 0 or bh <= 0:
            continue

        det_type = det.get("type", "overlay")
        color = type_colors.get(det_type, (0, 165, 255))
        confidence = float(det.get("confidence", 0))
        label = det.get("label", "Watermark")

        # Draw rectangle
        thickness = max(2, min(4, w // 300))
        cv2.rectangle(preview, (x, y), (x + bw, y + bh), color, thickness)

        # Label background
        conf_pct = int(confidence * 100)
        label_text = f"{label[:25]} ({conf_pct}%)"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.4, min(0.7, w / 1200))
        text_thickness = max(1, thickness - 1)
        (text_w, text_h), _ = cv2.getTextSize(label_text, font, font_scale, text_thickness)

        # Position label above box if possible
        label_y = y - 8 if y > text_h + 12 else y + bh + text_h + 8
        label_x = max(0, min(x, w - text_w - 4))

        # Background rectangle for label
        cv2.rectangle(
            preview,
            (label_x - 2, label_y - text_h - 4),
            (label_x + text_w + 4, label_y + 4),
            color,
            -1,
        )
        cv2.putText(
            preview,
            label_text,
            (label_x, label_y),
            font,
            font_scale,
            (255, 255, 255),
            text_thickness,
            cv2.LINE_AA,
        )

    ok, encoded = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok or encoded is None:
        return image_bytes
    return encoded.tobytes()
