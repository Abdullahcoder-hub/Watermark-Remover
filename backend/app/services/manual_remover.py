"""
Manual watermark removal for PDF documents.

Handles both vector and raster/scanned PDF pages with surgical content preservation:
- Preserves embedded photographs and illustrations: when a selection overlaps an
  embedded image, the watermark region inside the image is extracted and inpainted
  (restoring surrounding texture and edges), rather than deleting or punching holes
  in the photograph.
- Preserves surrounding vector text, headers, lines, and signatures outside the selection.
- Correctly maps fractional preview coordinates to PDF page coordinates, accounting for
  page cropbox origin, rotation, and dimensions.
- Multi-page selection ("apply to all pages") validates page orientation and aspect ratio,
  avoiding blind coordinate reuse on mismatched pages.
"""
from __future__ import annotations

import gc
import logging
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.manual import ManualRegion
from app.services.image_inpainting import build_smart_mask, inpaint_frame
from app.services.inpainting import InpaintingError, decode_image, encode_png, inpaint
from app.services.mask_refiner import refine_scanned_mask, refine_vector_regions

logger = logging.getLogger("document_cleaner")

_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE
_IMAGES_REMOVE = fitz.PDF_REDACT_IMAGE_REMOVE
_IMAGES_NONE = fitz.PDF_REDACT_IMAGE_NONE
_GRAPHICS_REMOVE = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED

MAX_INPAINT_AREA_FRACTION = 0.35
MAX_REDACTABLE_IMAGE_COVERAGE = 0.50


class ManualRemovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _regions_for_document(
    pdf: fitz.Document,
    regions: list[ManualRegion],
    apply_to_all_pages: bool,
) -> list[ManualRegion]:
    """
    Expand regions across document pages.
    When apply_to_all_pages is True, checks orientation and aspect ratio compatibility
    before applying coordinates to other pages.
    """
    if not apply_to_all_pages:
        return regions

    if not regions:
        return []

    # Reference page for coordinate scaling
    ref_region = regions[0]
    ref_page_idx = max(0, min(pdf.page_count - 1, ref_region.page - 1))
    ref_page = pdf[ref_page_idx]
    ref_rect = ref_page.rect
    ref_aspect = ref_rect.width / max(ref_rect.height, 1.0)

    # Collect source region geometries from the reference page
    ref_regions = [r for r in regions if r.page == ref_region.page] or [ref_region]

    expanded: list[ManualRegion] = []
    for page_number in range(1, pdf.page_count + 1):
        target_page = pdf[page_number - 1]
        target_rect = target_page.rect
        target_aspect = target_rect.width / max(target_rect.height, 1.0)

        # If page orientation differs significantly (e.g. landscape vs portrait > 15%),
        # skip applying blind coordinates to avoid destroying content
        aspect_diff = abs(ref_aspect - target_aspect) / max(ref_aspect, 0.001)
        if aspect_diff > 0.15:
            logger.warning(
                "multi_page_selection_skipped_mismatched_page ref_page=%s target_page=%s ref_aspect=%.2f tgt_aspect=%.2f",
                ref_region.page,
                page_number,
                ref_aspect,
                target_aspect,
            )
            continue

        for r in ref_regions:
            expanded.append(
                ManualRegion(
                    page=page_number,
                    x0=r.x0,
                    y0=r.y0,
                    x1=r.x1,
                    y1=r.y1,
                )
            )

    return expanded if expanded else regions


def _to_page_rect(page: fitz.Page, rx0: float, ry0: float, rx1: float, ry1: float) -> fitz.Rect:
    """Map fractional coordinates [0, 1] to actual page coordinates considering non-zero origins."""
    rect = page.rect
    x0 = rect.x0 + min(rx0, rx1) * rect.width
    y0 = rect.y0 + min(ry0, ry1) * rect.height
    x1 = rect.x0 + max(rx0, rx1) * rect.width
    y1 = rect.y0 + max(ry0, ry1) * rect.height
    return fitz.Rect(x0, y0, x1, y1)


def _redact_page(
    pdf: fitz.Document,
    page: fitz.Page,
    regions: list[ManualRegion],
) -> None:
    """
    Surgically remove manual watermark regions on a vector / hybrid PDF page.
    Preserves embedded photographs and illustrations via inpainting rather than deletion.
    """
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return

    # Refine vector regions (tight snapping to text spans without swallowing photos)
    refined_tuples = refine_vector_regions(page, [(r.x0, r.y0, r.x1, r.y1) for r in regions])
    region_rects = [_to_page_rect(page, rx0, ry0, rx1, ry1) for rx0, ry0, rx1, ry1 in refined_tuples]

    # Inspect embedded images on the page
    images_info = page.get_image_info(xrefs=True)
    inpainted_xrefs: set[int] = set()

    for image_info in images_info:
        xref = image_info.get("xref")
        bbox = image_info.get("bbox")
        if not xref or not bbox:
            continue

        img_rect = fitz.Rect(bbox)
        if img_rect.is_empty:
            continue

        # Check intersection with each selection region
        for r_rect in region_rects:
            if not img_rect.intersects(r_rect):
                continue

            inter = img_rect & r_rect
            if inter.is_empty:
                continue

            img_area = max(img_rect.width * img_rect.height, 1.0)
            inter_area = inter.width * inter.height
            coverage_of_img = inter_area / img_area

            # If the image is a small standalone watermark object completely inside the selection
            if coverage_of_img > 0.95 and (img_rect in r_rect or coverage_of_img > 0.98):
                try:
                    page.delete_image(xref)
                    inpainted_xrefs.add(xref)
                    break
                except Exception as exc:
                    logger.debug("delete_overlay_image_failed xref=%s: %s", xref, exc)

            # The image is a photograph or illustration containing a watermark
            try:
                base = pdf.extract_image(xref)
                raw_bytes = base.get("image")
                if not raw_bytes:
                    continue

                img_arr = decode_image(raw_bytes)
                if img_arr is None or img_arr.size == 0:
                    continue

                H, W = img_arr.shape[:2]
                # Map intersection to image's internal pixel space
                px0 = max(0, min(W - 1, int(round((inter.x0 - img_rect.x0) / img_rect.width * W))))
                py0 = max(0, min(H - 1, int(round((inter.y0 - img_rect.y0) / img_rect.height * H))))
                px1 = max(px0 + 1, min(W, int(round((inter.x1 - img_rect.x0) / img_rect.width * W))))
                py1 = max(py0 + 1, min(H, int(round((inter.y1 - img_rect.y0) / img_rect.height * H))))

                # Inpaint the watermark within the photograph using smart stroke mask
                bbox_dict = [{"x": px0, "y": py0, "width": px1 - px0, "height": py1 - py0}]
                mask = build_smart_mask(img_arr, bbox_dict, refine_strokes=True)
                if mask.any():
                    restored_img = inpaint_frame(img_arr, mask)
                    restored_bytes = encode_png(restored_img)
                    page.replace_image(xref, stream=restored_bytes)
                    inpainted_xrefs.add(xref)
                    logger.info("inpainted_photo_in_pdf page=%s xref=%s bbox=%s", page.number + 1, xref, bbox_dict)
            except Exception as exc:
                logger.warning("inpaint_embedded_image_failed page=%s xref=%s: %s", page.number + 1, xref, exc)

    # Redact vector text and lines inside the selection
    # Do NOT delete images during redaction if they were preserved/inpainted
    for region_rect in region_rects:
        if region_rect.is_empty:
            continue
        page.add_redact_annot(region_rect, fill=None)

    # Keep images untouched so restored photos and adjacent figures remain completely intact
    page.apply_redactions(images=_IMAGES_NONE, graphics=_GRAPHICS_REMOVE, text=_TEXT_REMOVE)


def _inpaint_page(pdf: fitz.Document, page: fitz.Page, xref: int, regions: list[ManualRegion]) -> None:
    """Inpaint a scanned full-page image using smart stroke mask."""
    region_rects = [_to_page_rect(page, r.x0, r.y0, r.x1, r.y1) for r in regions]

    # Step 1: Remove small overlay images inside the selection
    page_area = max(page.rect.width * page.rect.height, 1.0)
    for image_info in page.get_image_info(xrefs=True):
        overlay_xref = image_info.get("xref")
        if not overlay_xref or overlay_xref == xref:
            continue
        bbox = image_info.get("bbox")
        if not bbox:
            continue
        image_rect = fitz.Rect(bbox)
        coverage = (image_rect.width * image_rect.height) / page_area
        if coverage > MAX_REDACTABLE_IMAGE_COVERAGE:
            continue
        if any(image_rect.intersects(r_rect) for r_rect in region_rects):
            try:
                page.delete_image(overlay_xref)
            except Exception:
                pass

    # Step 2: Extract scan image and inpaint watermark
    base = pdf.extract_image(xref)
    image = decode_image(base["image"])
    if image is None:
        raise ManualRemovalError("DECODE_FAILED", "Could not decode scanned page image.")

    mask, masked_fraction = refine_scanned_mask(
        image, [(r.x0, r.y0, r.x1, r.y1) for r in regions]
    )

    if masked_fraction > MAX_INPAINT_AREA_FRACTION:
        raise ManualRemovalError(
            "SELECTION_TOO_LARGE",
            f"This selection covers {masked_fraction:.0%} of the page. On a scanned page, restoring "
            f"an area this large isn't possible — there's no real content to reconstruct it from, and "
            f"the result would just be a blank patch. Try a tighter box around just the watermark.",
        )

    restored = inpaint(image, mask)
    restored_bytes = encode_png(restored)
    page.replace_image(xref, stream=restored_bytes)


def remove_manual_regions(
    source: Path | bytes,
    regions: list[ManualRegion],
    apply_to_all_pages: bool,
    scanned_pages: dict[int, int] | None = None,
    progress_callback: object = None,
) -> tuple[bytes, list[int]]:
    """
    Remove everything inside each manually-selected region from a PDF document.
    Preserves embedded photographs, text, and graphics outside the selected area.
    """
    scanned_pages = scanned_pages or {}
    pages_affected: list[int] = []

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ManualRemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            all_regions = _regions_for_document(pdf, regions, apply_to_all_pages)

            regions_by_page: dict[int, list[ManualRegion]] = defaultdict(list)
            for region in all_regions:
                if region.page < 1 or region.page > pdf.page_count:
                    continue
                regions_by_page[region.page].append(region)

            if not regions_by_page:
                raise ManualRemovalError(
                    "INVALID_PAGE",
                    f"No valid pages in the selection (document has {pdf.page_count} pages).",
                )

            total_target_pages = len(regions_by_page)
            for idx, (page_number, page_regions) in enumerate(regions_by_page.items()):
                if callable(progress_callback):
                    progress_callback(
                        idx + 1,
                        total_target_pages,
                        f"Applying manual removal — page {page_number} of {pdf.page_count}",
                    )

                page = pdf[page_number - 1]

                if page_number in scanned_pages:
                    _inpaint_page(pdf, page, scanned_pages[page_number], page_regions)
                else:
                    _redact_page(pdf, page, page_regions)

                pages_affected.append(page_number)
                if (idx + 1) % 5 == 0:
                    gc.collect()

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except (ManualRemovalError, InpaintingError) as exc:
        raise ManualRemovalError(exc.code, exc.message) from exc
    except Exception as exc:
        logger.exception("manual_removal_failed: %s", exc)
        raise ManualRemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected)
