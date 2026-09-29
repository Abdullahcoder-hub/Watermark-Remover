"""
Intelligent Mask Refiner & Adaptive Guidance Snapping (Computer Vision).

Upgrades manual tracing into a guidance region:
- For Scanned/Raster Pages: Analyzes local pixels, gradients, color contrast,
  and connected components to adaptively expand/refine the mask around the complete
  watermark strokes without damaging nearby legitimate text.
- For Vector/Text Pages: Snaps approximate user selections to complete text spans
  and vector/image object boundaries so characters are not sliced or clipped.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger("document_cleaner")

# Adaptive expansion margins
ROI_EXPANSION_MARGIN_RATIO = 0.08
MIN_STROKE_AREA_PIXELS = 4
MAX_COMPONENT_AREA_RATIO = 0.25


def refine_scanned_mask(
    image: np.ndarray,
    regions_fraction: list[tuple[float, float, float, float]],
) -> tuple[np.ndarray, float]:
    """
    Intelligently refine manual guidance regions on a scanned image using
    connected component analysis, gradient edge detection, and morphological dilation.

    Returns:
        (binary_mask, masked_fraction)
        - binary_mask: uint8 image (same HxW as image), 255 for watermark pixels, 0 elsewhere.
        - masked_fraction: float ratio of masked pixels to total image pixels.
    """
    height, width = image.shape[:2]
    total_pixels = height * width
    final_mask = np.zeros((height, width), dtype=np.uint8)

    if total_pixels == 0 or not regions_fraction:
        return final_mask, 0.0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 and image.shape[2] == 3 else image

    for x0, y0, x1, y1 in regions_fraction:
        px0 = int(max(0.0, min(1.0, x0)) * width)
        py0 = int(max(0.0, min(1.0, y0)) * height)
        px1 = int(max(0.0, min(1.0, x1)) * width)
        py1 = int(max(0.0, min(1.0, y1)) * height)

        px0, px1 = min(px0, px1), max(px0, px1)
        py0, py1 = min(py0, py1), max(py0, py1)

        sel_w = px1 - px0
        sel_h = py1 - py0
        if sel_w <= 2 or sel_h <= 2:
            continue

        # Expanded ROI to search for connected strokes that cross the selection boundary
        margin_x = int(sel_w * ROI_EXPANSION_MARGIN_RATIO)
        margin_y = int(sel_h * ROI_EXPANSION_MARGIN_RATIO)

        roi_x0 = max(0, px0 - margin_x)
        roi_y0 = max(0, py0 - margin_y)
        roi_x1 = min(width, px1 + margin_x)
        roi_y1 = min(height, py1 + margin_y)

        roi_gray = gray[roi_y0:roi_y1, roi_x0:roi_x1]
        if roi_gray.size == 0:
            final_mask[py0:py1, px0:px1] = 255
            continue

        try:
            # 1. Estimate background paper intensity (median of outer ROI boundary)
            border_pixels = np.concatenate([
                roi_gray[0, :],
                roi_gray[-1, :],
                roi_gray[:, 0],
                roi_gray[:, -1],
            ])
            bg_val = float(np.median(border_pixels)) if border_pixels.size > 0 else 255.0

            # 2. Extract foreground watermark strokes / stamps (both dark and light/colored stamps)
            diff = np.abs(roi_gray.astype(np.float32) - bg_val)
            norm_diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

            # Otsu thresholding + Adaptive thresholding hybrid
            _, otsu_thresh = cv2.threshold(norm_diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            adapt_thresh = cv2.adaptiveThreshold(
                roi_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
            )

            combined_fg = cv2.bitwise_or(otsu_thresh, adapt_thresh)

            # 3. Connected Components Analysis
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(combined_fg, connectivity=8)

            roi_mask = np.zeros_like(roi_gray, dtype=np.uint8)
            guidance_box_local_x0 = px0 - roi_x0
            guidance_box_local_y0 = py0 - roi_y0
            guidance_box_local_x1 = px1 - roi_x0
            guidance_box_local_y1 = py1 - roi_y0

            matched_components = 0

            for lbl in range(1, num_labels):
                comp_x = stats[lbl, cv2.CC_STAT_LEFT]
                comp_y = stats[lbl, cv2.CC_STAT_TOP]
                comp_w = stats[lbl, cv2.CC_STAT_WIDTH]
                comp_h = stats[lbl, cv2.CC_STAT_HEIGHT]
                comp_area = stats[lbl, cv2.CC_STAT_AREA]

                if comp_area < MIN_STROKE_AREA_PIXELS:
                    continue

                # Must not dominate entire page
                if comp_area > total_pixels * MAX_COMPONENT_AREA_RATIO:
                    continue

                # Check intersection with the user's guidance box
                ix0 = max(comp_x, guidance_box_local_x0)
                iy0 = max(comp_y, guidance_box_local_y0)
                ix1 = min(comp_x + comp_w, guidance_box_local_x1)
                iy1 = min(comp_y + comp_h, guidance_box_local_y1)

                if ix1 > ix0 and iy1 > iy0:
                    # Component touches/overlaps user guidance region: include it
                    roi_mask[labels == lbl] = 255
                    matched_components += 1

            if matched_components > 0:
                # Morphological close and slight dilation to bridge character gaps and cover stroke edges
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
                refined_roi = cv2.morphologyEx(roi_mask, cv2.MORPH_CLOSE, kernel)
                refined_roi = cv2.dilate(refined_roi, kernel, iterations=1)

                # Ensure the user's core core selection center is covered
                core_margin = 2
                final_mask[roi_y0:roi_y1, roi_x0:roi_x1] = cv2.bitwise_or(
                    final_mask[roi_y0:roi_y1, roi_x0:roi_x1], refined_roi
                )
                final_mask[py0 + core_margin : py1 - core_margin, px0 + core_margin : px1 - core_margin] = 255
            else:
                # Fallback to direct guidance rectangle
                final_mask[py0:py1, px0:px1] = 255

        except Exception as exc:
            logger.warning("refine_scanned_mask_fallback: %s", exc)
            final_mask[py0:py1, px0:px1] = 255

    masked_fraction = float((final_mask > 0).sum()) / float(total_pixels)
    return final_mask, masked_fraction


def refine_vector_regions(
    page: fitz.Page,
    regions_fraction: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    """
    For vector PDFs, snap fractional guidance regions to complete intersecting
    text spans and image objects so letters and words are cleanly removed without clipping.
    """
    page_w = page.rect.width
    page_h = page.rect.height
    if page_w <= 0 or page_h <= 0:
        return regions_fraction

    refined_regions: list[tuple[float, float, float, float]] = []

    # Extract all text spans
    text_spans: list[tuple[float, float, float, float]] = []
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        if block.get("type") == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox")
                    if bbox:
                        text_spans.append((bbox[0], bbox[1], bbox[2], bbox[3]))

    # Extract image bboxes
    image_bboxes: list[tuple[float, float, float, float]] = []
    for img_info in page.get_image_info(xrefs=True):
        bbox = img_info.get("bbox")
        if bbox:
            image_bboxes.append((bbox[0], bbox[1], bbox[2], bbox[3]))

    for x0, y0, x1, y1 in regions_fraction:
        rx0, ry0 = x0 * page_w, y0 * page_h
        rx1, ry1 = x1 * page_w, y1 * page_h

        rx0, rx1 = min(rx0, rx1), max(rx0, rx1)
        ry0, ry1 = min(ry0, ry1), max(ry0, ry1)

        expanded_x0, expanded_y0 = rx0, ry0
        expanded_x1, expanded_y1 = rx1, ry1

        # Check overlapping text spans
        for tx0, ty0, tx1, ty1 in text_spans:
            ix0 = max(rx0, tx0)
            iy0 = max(ry0, ty0)
            ix1 = min(rx1, tx1)
            iy1 = min(ry1, ty1)

            if ix1 > ix0 and iy1 > iy0:
                span_area = max(1.0, (tx1 - tx0) * (ty1 - ty0))
                inter_area = (ix1 - ix0) * (iy1 - iy0)
                # If guidance overlaps >= 20% of text span or span center is inside
                span_cx = (tx0 + tx1) / 2
                span_cy = (ty0 + ty1) / 2
                if (inter_area / span_area >= 0.20) or (rx0 <= span_cx <= rx1 and ry0 <= span_cy <= ry1):
                    expanded_x0 = min(expanded_x0, tx0)
                    expanded_y0 = min(expanded_y0, ty0)
                    expanded_x1 = max(expanded_x1, tx1)
                    expanded_y1 = max(expanded_y1, ty1)

        # Check overlapping small overlay images
        for ix0_img, iy0_img, ix1_img, iy1_img in image_bboxes:
            img_area = (ix1_img - ix0_img) * (iy1_img - iy0_img)
            if img_area < (page_w * page_h * 0.4):  # small/moderate overlay
                ix0 = max(rx0, ix0_img)
                iy0 = max(ry0, iy0_img)
                ix1 = min(rx1, ix1_img)
                iy1 = min(ry1, iy1_img)
                if ix1 > ix0 and iy1 > iy0:
                    inter_area = (ix1 - ix0) * (iy1 - iy0)
                    if inter_area / img_area >= 0.25:
                        expanded_x0 = min(expanded_x0, ix0_img)
                        expanded_y0 = min(expanded_y0, iy0_img)
                        expanded_x1 = max(expanded_x1, ix1_img)
                        expanded_y1 = max(expanded_y1, iy1_img)

        # Convert back to fractional coordinates
        refined_regions.append((
            round(max(0.0, expanded_x0 / page_w), 4),
            round(max(0.0, expanded_y0 / page_h), 4),
            round(min(1.0, expanded_x1 / page_w), 4),
            round(min(1.0, expanded_y1 / page_h), 4),
        ))

    return refined_regions
