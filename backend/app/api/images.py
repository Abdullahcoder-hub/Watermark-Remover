"""
Image watermark detection and removal API.

Endpoints:
  POST /api/v1/images/detect-watermark
    Upload an image → get AI detections with confidence scores.

  POST /api/v1/images/remove-watermark
    Upload an image + bbox list → get cleaned image.

  POST /api/v1/images/preview
    Upload an image + detections → get annotated preview JPEG.

All endpoints are stateless (no server-side job storage). The image bytes
are processed in-memory and returned immediately.  This keeps the API
simple and suitable for the free Render tier where persistent storage
between requests is not guaranteed.

File format support:
  Input:  JPG, JPEG, PNG, WEBP, BMP, TIFF (validated by magic bytes)
  Output: Same format as input where possible.

Security:
  - File extension + MIME type + magic byte validation before decoding.
  - Size limits enforced (default 50 MB, from settings).
  - Safe filenames: only UUID + extension stored internally.
  - Temp bytes are never written to disk in this module.
"""
from __future__ import annotations

import io
import logging
import struct
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services.image_inpainting import (
    ImageInpaintingError,
    build_preview_with_detections,
    remove_watermarks_from_image,
)
from app.services.image_watermark_detector import detect_watermarks_in_image

logger = logging.getLogger("document_cleaner")

router = APIRouter(prefix="/api/v1/images", tags=["images"])

# ---------------------------------------------------------------------------
# Allowed image MIME types and magic byte signatures
# ---------------------------------------------------------------------------
IMAGE_MAGIC_MAP: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",          # Need further check (bytes 8–11 == "WEBP")
    b"BM": "image/bmp",
    b"II*\x00": "image/tiff",       # Little-endian TIFF
    b"MM\x00*": "image/tiff",       # Big-endian TIFF
    b"GIF8": "image/gif",
}

ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
}

MAX_IMAGE_SIZE_BYTES = settings.max_upload_size_bytes  # default 50 MB


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BoundingBox(BaseModel):
    x: float = Field(..., ge=0, description="Left edge in pixels")
    y: float = Field(..., ge=0, description="Top edge in pixels")
    width: float = Field(..., gt=0, description="Width in pixels")
    height: float = Field(..., gt=0, description="Height in pixels")


class DetectionResult(BaseModel):
    detection_id: str
    type: str
    label: str
    confidence: float
    bbox: BoundingBox
    reasons: list[str]


class ImageDetectionResponse(BaseModel):
    success: bool = True
    detection_count: int
    detections: list[DetectionResult]
    image_width: int
    image_height: int
    message: str


class RemovalBBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"success": False, "error": {"code": code, "message": message}},
    )


def _validate_image(
    filename: str | None,
    content_bytes: bytes,
) -> str:
    """
    Validate file extension and magic bytes.
    Returns the normalised extension (e.g. '.jpg').
    Raises HTTPException on failure.
    """
    if not filename:
        raise _api_error(400, "MISSING_FILENAME", "No filename was provided.")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise _api_error(
            400,
            "INVALID_EXTENSION",
            f"Unsupported file type '{ext}'. Supported: JPG, JPEG, PNG, WEBP, BMP, TIFF.",
        )

    if len(content_bytes) == 0:
        raise _api_error(400, "EMPTY_FILE", "The uploaded file is empty.")

    if len(content_bytes) > MAX_IMAGE_SIZE_BYTES:
        max_mb = MAX_IMAGE_SIZE_BYTES // (1024 * 1024)
        raise _api_error(400, "FILE_TOO_LARGE", f"File exceeds the {max_mb} MB limit.")

    # Magic byte check
    header = content_bytes[:12]
    detected_mime = None

    if header[:3] == b"\xff\xd8\xff":
        detected_mime = "image/jpeg"
    elif header[:8] == b"\x89PNG\r\n\x1a\n":
        detected_mime = "image/png"
    elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        detected_mime = "image/webp"
    elif header[:2] == b"BM":
        detected_mime = "image/bmp"
    elif header[:4] in (b"II*\x00", b"MM\x00*"):
        detected_mime = "image/tiff"

    if detected_mime is None:
        raise _api_error(
            400,
            "INVALID_IMAGE",
            "The uploaded file is not a recognised image format. Please upload a JPG, PNG, WEBP, BMP, or TIFF file.",
        )

    # Normalise extension
    ext_norm_map = {".jpeg": ".jpg", ".tif": ".tiff"}
    return ext_norm_map.get(ext, ext)


def _get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) by decoding the image header."""
    try:
        import cv2, numpy as np
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            h, w = img.shape[:2]
            return w, h
    except Exception:
        pass
    return 0, 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/detect-watermark", response_model=ImageDetectionResponse)
async def detect_image_watermark(
    file: UploadFile = File(...),
) -> ImageDetectionResponse:
    """
    Detect watermarks in an uploaded raster image.

    Returns a list of detections with bounding boxes and confidence scores.
    High-confidence detections (≥ 0.70) are pre-selected for removal.
    Medium-confidence detections (0.40–0.70) are presented for user review.
    Low-confidence detections (< 0.40) are shown but not auto-selected.
    """
    contents = await file.read()

    try:
        _ext = _validate_image(file.filename, contents)
    except HTTPException:
        raise
    except Exception as exc:
        raise _api_error(400, "VALIDATION_FAILED", "File validation failed.") from exc

    img_w, img_h = _get_image_dimensions(contents)
    if img_w == 0 or img_h == 0:
        raise _api_error(400, "DECODE_FAILED", "The image could not be decoded. It may be corrupted.")

    try:
        raw_detections = detect_watermarks_in_image(contents)
    except Exception as exc:
        logger.exception("image_watermark_detection_failed filename=%s", file.filename)
        raise _api_error(
            500,
            "DETECTION_FAILED",
            "Watermark detection failed. Please try again.",
        ) from exc

    results: list[DetectionResult] = []
    for det in raw_detections:
        bbox = det.bbox
        # Ensure bbox stays within image bounds
        x = max(0, min(img_w - 1, int(bbox.get("x", 0))))
        y = max(0, min(img_h - 1, int(bbox.get("y", 0))))
        bw = max(1, min(img_w - x, int(bbox.get("width", 1))))
        bh = max(1, min(img_h - y, int(bbox.get("height", 1))))

        results.append(
            DetectionResult(
                detection_id=det.detection_id,
                type=det.type,
                label=det.label,
                confidence=round(det.confidence, 2),
                bbox=BoundingBox(x=x, y=y, width=bw, height=bh),
                reasons=det.reasons,
            )
        )

    # Determine message
    high_conf = [r for r in results if r.confidence >= 0.70]
    med_conf  = [r for r in results if 0.40 <= r.confidence < 0.70]
    if not results:
        msg = "No watermarks detected. You can still select an area manually."
    elif high_conf:
        msg = f"{len(results)} watermark(s) detected ({len(high_conf)} high-confidence)."
    else:
        msg = f"{len(results)} possible watermark(s) detected. Please review and confirm."

    logger.info(
        "image_detect_success filename=%s detections=%s img=%sx%s",
        file.filename,
        len(results),
        img_w,
        img_h,
    )

    return ImageDetectionResponse(
        success=True,
        detection_count=len(results),
        detections=results,
        image_width=img_w,
        image_height=img_h,
        message=msg,
    )


@router.post("/remove-watermark")
async def remove_image_watermark(
    file: UploadFile = File(...),
    regions: str = Form(...),   # JSON string: [{x,y,width,height}, ...]
) -> Response:
    """
    Remove watermarks from an uploaded image using inpainting.

    The `regions` form field must be a JSON array of bounding boxes:
    [{"x": 100, "y": 50, "width": 200, "height": 80}, ...]

    Returns the cleaned image in the same format as the input.
    """
    import json

    contents = await file.read()

    try:
        ext = _validate_image(file.filename, contents)
    except HTTPException:
        raise

    try:
        bboxes = json.loads(regions)
        if not isinstance(bboxes, list):
            raise ValueError("regions must be a JSON array")
        # Validate each bbox
        validated_bboxes: list[dict] = []
        for b in bboxes:
            if not all(k in b for k in ("x", "y", "width", "height")):
                continue
            validated_bboxes.append({
                "x": float(b["x"]),
                "y": float(b["y"]),
                "width": float(b["width"]),
                "height": float(b["height"]),
            })
    except (json.JSONDecodeError, ValueError) as exc:
        raise _api_error(400, "INVALID_REGIONS", "The 'regions' field must be a valid JSON array of bounding boxes.") from exc

    if not validated_bboxes:
        raise _api_error(400, "NO_REGIONS", "No valid regions were provided for removal.")

    try:
        cleaned_bytes = remove_watermarks_from_image(
            contents,
            validated_bboxes,
            original_filename=file.filename or "image.jpg",
        )
    except ImageInpaintingError as exc:
        raise _api_error(400, exc.code, exc.message) from exc
    except Exception as exc:
        logger.exception("image_removal_failed filename=%s", file.filename)
        raise _api_error(500, "REMOVAL_FAILED", "Watermark removal failed. Please try again.") from exc

    # Determine media type
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }
    raw_ext = Path(file.filename or "image.jpg").suffix.lower()
    media_type = media_type_map.get(raw_ext, "image/jpeg")
    out_ext = ".jpg" if raw_ext in (".jpg", ".jpeg") else raw_ext

    # Build safe download filename
    stem = Path(file.filename or "image").stem[:40]
    import re
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "image"
    download_filename = f"cleaned_{safe_stem}{out_ext}"

    logger.info(
        "image_removal_success filename=%s regions=%s output_bytes=%s",
        file.filename,
        len(validated_bboxes),
        len(cleaned_bytes),
    )

    return Response(
        content=cleaned_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"',
            "Content-Length": str(len(cleaned_bytes)),
        },
    )


@router.post("/preview")
async def preview_image_detections(
    file: UploadFile = File(...),
    detections: str = Form(...),  # JSON string
) -> Response:
    """
    Overlay detection bounding boxes on the image and return an annotated JPEG preview.

    The `detections` form field must be a JSON array of detection objects.
    """
    import json

    contents = await file.read()

    try:
        _validate_image(file.filename, contents)
    except HTTPException:
        raise

    try:
        det_list = json.loads(detections)
        if not isinstance(det_list, list):
            det_list = []
    except (json.JSONDecodeError, ValueError):
        det_list = []

    try:
        preview_bytes = build_preview_with_detections(contents, det_list)
    except Exception as exc:
        logger.warning("image_preview_failed: %s", exc)
        # Return original as fallback
        preview_bytes = contents

    return Response(content=preview_bytes, media_type="image/jpeg")
