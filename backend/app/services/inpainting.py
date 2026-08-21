"""
Image restoration via classical inpainting (Phase 6, Case C).

Used when a watermark sits on a scanned page — where "the watermark"
is baked into pixels rather than existing as a separate text/image
object. The only safe way to remove it without destroying the page's
actual scanned content is: extract the original-resolution embedded
image, mask out the selected region(s), inpaint, and write the result
back to the same PDF image object (same xref, same placement) via
PyMuPDF's replace_image — everything else about the page is untouched.

Uses OpenCV's classical Telea inpainting (cv2.INPAINT_TELEA), not a
learned/generative model, matching the "free/open-source, no AI
dependency for core functionality" constraint. Deep-learning-based
inpainting is deliberately out of scope here.
"""
import cv2
import numpy as np

# Empirically reasonable default: large enough to blend cleanly across
# a stamp-sized watermark, small enough to stay fast on typical scans.
DEFAULT_INPAINT_RADIUS = 7


class InpaintingError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def decode_image(image_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise InpaintingError("INVALID_IMAGE", "The scanned page image could not be decoded.")
    return image


def build_mask(
    image_shape: tuple[int, int],
    regions_fraction: list[tuple[float, float, float, float]],
) -> np.ndarray:
    """
    Build a binary mask (same pixel size as the image) with every
    fractional region (x0, y0, x1, y1 in [0, 1], page-relative) filled
    in white — the area cv2.inpaint will reconstruct.
    """
    height, width = image_shape
    mask = np.zeros((height, width), dtype=np.uint8)
    for x0, y0, x1, y1 in regions_fraction:
        px0, py0 = int(x0 * width), int(y0 * height)
        px1, py1 = int(x1 * width), int(y1 * height)
        px0, px1 = sorted((max(0, px0), min(width, px1)))
        py0, py1 = sorted((max(0, py0), min(height, py1)))
        if px1 > px0 and py1 > py0:
            mask[py0:py1, px0:px1] = 255
    return mask


def inpaint(image: np.ndarray, mask: np.ndarray, radius: int = DEFAULT_INPAINT_RADIUS) -> np.ndarray:
    if not mask.any():
        return image
    return cv2.inpaint(image, mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)


def encode_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise InpaintingError("ENCODE_FAILED", "The restored image could not be encoded.")
    return encoded.tobytes()
