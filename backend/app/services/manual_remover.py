"""
Manual watermark removal (Phase 5, extended in Phase 6 for scanned pages).

Unlike the scored, type-scoped automatic detectors, manual selection
is intentionally blunt: the user has visually confirmed a region, so
everything inside it should go. But *how* it's removed depends on the
page:

- Normal pages (Case A/B): redact the region — text, raster images,
  and vector graphics inside the box are deleted via PyMuPDF redaction.
- Scanned pages (Case C): redaction is unsafe here. Verified directly —
  a redaction box that only partially overlaps a full-page image
  deletes the ENTIRE image object, not just the covered pixels. Since
  a scanned page's "image" IS the page's content, that would destroy
  the whole page over a small watermark stamp. Instead, the selected
  region is masked and filled with OpenCV inpainting (see
  inpainting.py), and the restored image replaces the original at the
  same xref -- everything else about the page is untouched. Separately,
  any *small* overlay image within the selection (e.g. a logo layered
  on top of the scan as its own image object, rather than baked into
  the scan's pixels — confirmed on a real CamScanner export) is deleted
  outright via precise per-object redaction, since inpainting the scan
  underneath it wouldn't touch a distinct object drawn on top.

Both paths run inside the same PyMuPDF document pass (one open, one
save), for the same reason Phase 4's combined remover does: an
intermediate garbage-collecting save renumbers xrefs, which would
break the scanned-page path's xref lookups if it ran as a second,
separate pass over already-saved bytes.
"""
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF

from app.schemas.manual import ManualRegion
from app.services.inpainting import InpaintingError, build_mask, decode_image, encode_png, inpaint

_TEXT_REMOVE = fitz.PDF_REDACT_TEXT_REMOVE
_IMAGES_REMOVE = fitz.PDF_REDACT_IMAGE_REMOVE
# "if touched" (not "if covered") because a manually drawn box is a
# deliberate, explicit selection -- any graphics the box overlaps
# should go, not only ones fully enclosed by it.
_GRAPHICS_REMOVE = fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED

# Classical inpainting (Telea) reconstructs a masked area from its
# surrounding pixels. It has no source data to work with once the
# masked area gets large relative to the image, and produces a
# washed-out/blank-looking result instead -- confirmed directly: a
# selection covering ~65% of a scanned page came back as a uniform
# foggy patch, indistinguishable from data loss even though nothing
# was silently destroyed by the removal logic itself. Rather than
# let that happen quietly, a selection this large on a scanned page
# is rejected with an explanation instead of "succeeding" into a
# ruined page.
MAX_INPAINT_AREA_FRACTION = 0.20


class ManualRemovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _regions_for_document(regions: list[ManualRegion], page_count: int, apply_to_all_pages: bool) -> list[ManualRegion]:
    if not apply_to_all_pages:
        return regions

    expanded: list[ManualRegion] = []
    for region in regions:
        for page_number in range(1, page_count + 1):
            expanded.append(ManualRegion(page=page_number, x0=region.x0, y0=region.y0, x1=region.x1, y1=region.y1))
    return expanded


# Same defense-in-depth as the automatic removal path
# (watermark_remover.py / image_remover.py): never let a redaction box
# delete an image that dominates the page, even on a page that wasn't
# classified as "scanned" — since that classification can be wrong
# (see SCANNED_IMAGE_COVERAGE_THRESHOLD's history in pdf_analyzer.py).
MAX_REDACTABLE_IMAGE_COVERAGE = 0.5


def _rects_overlap(a: "fitz.Rect", b: "fitz.Rect") -> bool:
    return a.intersects(b)


def _redact_page(page: "fitz.Page", regions: list[ManualRegion], page_width: float, page_height: float) -> None:
    page_area = page_width * page_height
    region_rects = [
        fitz.Rect(r.x0 * page_width, r.y0 * page_height, r.x1 * page_width, r.y1 * page_height) for r in regions
    ]

    if page_area > 0:
        for image_info in page.get_image_info(xrefs=True):
            bbox = image_info.get("bbox")
            if not bbox:
                continue
            image_rect = fitz.Rect(bbox)
            coverage = (image_rect.width * image_rect.height) / page_area
            if coverage <= MAX_REDACTABLE_IMAGE_COVERAGE:
                continue
            if any(_rects_overlap(image_rect, region_rect) for region_rect in region_rects):
                raise ManualRemovalError(
                    "SELECTION_OVERLAPS_PAGE_CONTENT",
                    "This selection overlaps an image that covers most of the page, which looks like "
                    "the page's actual content rather than a watermark. Deleting it would destroy the "
                    "page. If this is a scanned document, try re-uploading it, or choose a smaller box "
                    "that avoids the main content area.",
                )

    for region_rect in region_rects:
        if region_rect.is_empty:
            continue
        page.add_redact_annot(region_rect, fill=None)
    page.apply_redactions(images=_IMAGES_REMOVE, graphics=_GRAPHICS_REMOVE, text=_TEXT_REMOVE)


def _inpaint_page(pdf: "fitz.Document", page: "fitz.Page", xref: int, regions: list[ManualRegion]) -> None:
    # Order and method matter here, both confirmed by direct testing:
    # apply_redactions() silently corrupts *other* images on the same
    # page -- even ones it was never asked to touch -- immediately
    # within the same session, well before any save. A page with a
    # dominant scan (xref A) and a small logo (xref B) lost BOTH images
    # after redacting only B. replace_image()-based calls don't have
    # this problem: they only affect the xref they're given. So overlay
    # removal here uses delete_image() (built on replace_image, not
    # redaction) instead of add_redact_annot()/apply_redactions().

    # Step 1: delete any SEPARATE small image overlapping the selection.
    # Confirmed directly on a real CamScanner export: the visible logo
    # is often its own small image object layered on top of the main
    # scan, not baked into the scan's pixels -- inpainting the dominant
    # image alone leaves such a logo completely untouched, since it's a
    # distinct object drawn on top. Small overlay images are safe to
    # clear this way; they're nowhere near large enough to trip
    # MAX_REDACTABLE_IMAGE_COVERAGE.
    page_area = page.rect.width * page.rect.height
    region_rects = [
        fitz.Rect(r.x0 * page.rect.width, r.y0 * page.rect.height, r.x1 * page.rect.width, r.y1 * page.rect.height)
        for r in regions
    ]

    if page_area > 0:
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
                continue  # not a small overlay -- leave it alone here
            if not any(image_rect.intersects(region_rect) for region_rect in region_rects):
                continue
            page.delete_image(overlay_xref)

    # Step 2: inpaint the dominant scan image for the selected region(s),
    # in case any part of the watermark is baked directly into the scan
    # itself rather than (or in addition to) a separate overlay image.
    base = pdf.extract_image(xref)
    image = decode_image(base["image"])
    height, width = image.shape[:2]

    mask = build_mask((height, width), [(r.x0, r.y0, r.x1, r.y1) for r in regions])

    masked_fraction = float((mask > 0).sum()) / float(height * width)
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
) -> tuple[bytes, list[int]]:
    """
    Remove everything inside each manually-selected region.

    `source` may be a path to a stored PDF, or raw PDF bytes (used when
    chaining after an earlier automatic-removal step).
    `scanned_pages` maps page_number -> xref for pages the caller has
    identified as scanned (see scanned_detector.py); those pages are
    inpainted instead of redacted. Pages not in this map use redaction.

    Returns (cleaned_pdf_bytes, pages_affected).
    """
    scanned_pages = scanned_pages or {}
    pages_affected: list[int] = []

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise ManualRemovalError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            all_regions = _regions_for_document(regions, pdf.page_count, apply_to_all_pages)

            regions_by_page: dict[int, list[ManualRegion]] = defaultdict(list)
            for region in all_regions:
                if region.page < 1 or region.page > pdf.page_count:
                    continue
                regions_by_page[region.page].append(region)

            if not regions_by_page:
                raise ManualRemovalError("INVALID_PAGE", f"No valid pages in the selection (document has {pdf.page_count} pages).")

            for page_number, page_regions in regions_by_page.items():
                page = pdf[page_number - 1]

                if page_number in scanned_pages:
                    _inpaint_page(pdf, page, scanned_pages[page_number], page_regions)
                else:
                    _redact_page(page, page_regions, page.rect.width, page.rect.height)

                pages_affected.append(page_number)

            cleaned_bytes = pdf.tobytes(garbage=4, deflate=True)
    except (ManualRemovalError, InpaintingError) as exc:
        raise ManualRemovalError(exc.code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF failure means the file couldn't be processed
        raise ManualRemovalError("PROCESSING_FAILED", "The document could not be processed.") from exc

    return cleaned_bytes, sorted(pages_affected)
