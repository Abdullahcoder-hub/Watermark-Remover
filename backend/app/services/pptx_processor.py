"""
PowerPoint (.pptx) analyzer, watermark detector, remover, and preview renderer.

Uses standard OpenXML presentation package inspection (zipfile + xml.etree.ElementTree + Pillow),
requiring zero external cloud APIs or tokens, running 100% locally and token-free.
"""
from __future__ import annotations

import io
import logging
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, PageAnalysis, TextObject
from app.schemas.manual import ManualRegion
from app.schemas.watermark import WatermarkCandidate

logger = logging.getLogger("document_cleaner")

# OpenXML Namespaces
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

NAMESPACES = {
    "p": NS_P,
    "a": NS_A,
    "r": NS_R,
}

# Register namespaces so ET serializes cleanly without ns0: prefixes
for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)
ET.register_namespace("", NS_P)

# 1 inch = 914400 EMUs, 1 pt = 12700 EMUs (72 pt per inch)
EMU_PER_PT = 12700
EMU_PER_INCH = 914400


class PptxProcessingError(Exception):
    """Raised when PPTX parsing or processing fails."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def is_pptx_file(path: Path | bytes) -> bool:
    """Check if the given path or bytes represents a valid PPTX zip package."""
    try:
        if isinstance(path, (str, Path)):
            with zipfile.ZipFile(path, "r") as zf:
                namelist = zf.namelist()
                return (
                    "ppt/presentation.xml" in namelist
                    and "[Content_Types].xml" in namelist
                )
        elif isinstance(path, bytes):
            with zipfile.ZipFile(io.BytesIO(path), "r") as zf:
                namelist = zf.namelist()
                return (
                    "ppt/presentation.xml" in namelist
                    and "[Content_Types].xml" in namelist
                )
    except Exception:
        return False
    return False


def get_pptx_slide_count(path: Path) -> int:
    """Quickly count slides in a PPTX presentation."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            slide_files = [n for n in zf.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)]
            return len(slide_files)
    except Exception:
        return 0


def _emu_to_pt(emu: int | float) -> float:
    return float(emu) / EMU_PER_PT


def _extract_slide_size(zf: zipfile.ZipFile) -> tuple[float, float]:
    """Extract slide width and height in points from ppt/presentation.xml."""
    try:
        if "ppt/presentation.xml" in zf.namelist():
            tree = ET.fromstring(zf.read("ppt/presentation.xml"))
            sldSz = tree.find(".//p:sldSz", NAMESPACES)
            if sldSz is not None:
                cx = int(sldSz.get("cx", "12192000"))
                cy = int(sldSz.get("cy", "6858000"))
                return _emu_to_pt(cx), _emu_to_pt(cy)
    except Exception as exc:
        logger.warning("Failed to parse ppt/presentation.xml sldSz: %s", exc)
    # Default 16:9 widescreen: 960 x 540 pt (13.33 x 7.5 in)
    return 960.0, 540.0


def _parse_shape_transform(sp: ET.Element) -> tuple[tuple[float, float, float, float], float]:
    """Extract bounding box (x0, y0, x1, y1 in pt) and rotation degrees from a shape."""
    xfrm = sp.find(".//p:spPr/a:xfrm", NAMESPACES)
    if xfrm is None:
        xfrm = sp.find(".//a:xfrm", NAMESPACES)
    if xfrm is None:
        return (0.0, 0.0, 0.0, 0.0), 0.0

    off = xfrm.find("a:off", NAMESPACES)
    ext = xfrm.find("a:ext", NAMESPACES)
    rot_attr = xfrm.get("rot", "0")

    x = _emu_to_pt(int(off.get("x", "0"))) if off is not None else 0.0
    y = _emu_to_pt(int(off.get("y", "0"))) if off is not None else 0.0
    w = _emu_to_pt(int(ext.get("cx", "0"))) if ext is not None else 0.0
    h = _emu_to_pt(int(ext.get("cy", "0"))) if ext is not None else 0.0
    rot = float(rot_attr) / 60000.0  # 60,000ths of a degree in OOXML

    return (round(x, 2), round(y, 2), round(x + w, 2), round(y + h, 2)), round(rot, 2)


def _extract_shape_text(sp: ET.Element) -> str:
    """Extract all text runs from a shape's txBody."""
    txBody = sp.find(".//p:txBody", NAMESPACES)
    if txBody is None:
        return ""
    text_parts: list[str] = []
    for p in txBody.findall(".//a:p", NAMESPACES):
        p_text = "".join(t.text or "" for t in p.findall(".//a:t", NAMESPACES))
        if p_text.strip():
            text_parts.append(p_text.strip())
    return " ".join(text_parts).strip()


def _get_layout_and_master_trees(
    zf: zipfile.ZipFile, slide_name: str
) -> list[tuple[ET.Element, dict[str, str], dict[str, str], str]]:
    """
    Return [(tree, media_rel_map, hyperlink_rel_map, file_name)]
    for layout and master linked to the given slide.
    """
    results: list[tuple[ET.Element, dict[str, str], dict[str, str], str]] = []
    slide_base = os.path.basename(slide_name)
    slide_rel_path = f"ppt/slides/_rels/{slide_base}.rels"
    if slide_rel_path not in zf.namelist():
        return results

    try:
        slide_rel_tree = ET.fromstring(zf.read(slide_rel_path))
        layout_name = None
        for rel in slide_rel_tree.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            if rel.get("Type", "").endswith("slideLayout"):
                target = rel.get("Target", "")
                layout_name = "ppt/" + target.replace("../", "")
                break

        if layout_name and layout_name in zf.namelist():
            layout_tree = ET.fromstring(zf.read(layout_name))
            layout_media_map: dict[str, str] = {}
            layout_hlink_map: dict[str, str] = {}
            layout_base = os.path.basename(layout_name)
            layout_rel_path = f"ppt/slideLayouts/_rels/{layout_base}.rels"
            master_name = None
            if layout_rel_path in zf.namelist():
                l_rel_tree = ET.fromstring(zf.read(layout_rel_path))
                for l_rel in l_rel_tree.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                    r_id = l_rel.get("Id", "")
                    target = l_rel.get("Target", "")
                    rel_type = l_rel.get("Type", "")
                    if target.startswith("../media/"):
                        layout_media_map[r_id] = "ppt/media/" + target[len("../media/"):]
                    elif target.startswith("media/"):
                        layout_media_map[r_id] = "ppt/" + target
                    elif rel_type.endswith("hyperlink"):
                        layout_hlink_map[r_id] = target
                    elif rel_type.endswith("slideMaster"):
                        master_name = "ppt/" + target.replace("../", "")
            results.append((layout_tree, layout_media_map, layout_hlink_map, layout_name))

            if master_name and master_name in zf.namelist():
                master_tree = ET.fromstring(zf.read(master_name))
                master_media_map: dict[str, str] = {}
                master_hlink_map: dict[str, str] = {}
                master_base = os.path.basename(master_name)
                master_rel_path = f"ppt/slideMasters/_rels/{master_base}.rels"
                if master_rel_path in zf.namelist():
                    m_rel_tree = ET.fromstring(zf.read(master_rel_path))
                    for m_rel in m_rel_tree.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                        r_id = m_rel.get("Id", "")
                        target = m_rel.get("Target", "")
                        rel_type = m_rel.get("Type", "")
                        if target.startswith("../media/"):
                            master_media_map[r_id] = "ppt/media/" + target[len("../media/"):]
                        elif target.startswith("media/"):
                            master_media_map[r_id] = "ppt/" + target
                        elif rel_type.endswith("hyperlink"):
                            master_hlink_map[r_id] = target
                results.append((master_tree, master_media_map, master_hlink_map, master_name))
    except Exception as exc:
        logger.debug("get_layout_and_master_error: %s", exc)

    return results


def analyze_pptx(
    document_id: str,
    path: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> DocumentAnalysisResponse:
    """
    Extract structure (text objects and image objects) from a PPTX file.
    Inspects slides, slide masters, and layouts.
    """
    if not is_pptx_file(path):
        raise PptxProcessingError("INVALID_PPTX", "The file is not a valid PowerPoint presentation.")

    try:
        with zipfile.ZipFile(path, "r") as zf:
            slide_width, slide_height = _extract_slide_size(zf)
            
            # Find and sort slide xml files (e.g. slide1.xml, slide2.xml)
            slide_entries: list[tuple[int, str]] = []
            for name in zf.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))
            slide_entries.sort(key=lambda item: item[0])
            if not slide_entries:
                raise PptxProcessingError(
                    "INVALID_PPTX",
                    "The PowerPoint presentation does not contain any slides.",
                )

            # Also inspect slide masters for watermark shapes
            master_entries = [n for n in zf.namelist() if re.match(r"^ppt/slideMasters/slideMaster\d+\.xml$", n)]

            master_text_objects: list[tuple[str, tuple[float, float, float, float], float]] = []
            for master_name in master_entries:
                try:
                    master_tree = ET.fromstring(zf.read(master_name))
                    for sp in master_tree.findall(".//p:sp", NAMESPACES):
                        txt = _extract_shape_text(sp)
                        if txt:
                            bbox, rot = _parse_shape_transform(sp)
                            master_text_objects.append((txt, bbox, rot))
                except Exception:
                    pass

            pages: list[PageAnalysis] = []
            total_text_objects = 0
            total_images = 0
            total_slides = max(len(slide_entries), 1)

            for slide_index, (_, slide_name) in enumerate(slide_entries, start=1):
                if progress_callback is not None:
                    progress_callback(
                        slide_index,
                        total_slides,
                        f"Analyzing PowerPoint — slide {slide_index} of {total_slides}",
                    )
                slide_xml = zf.read(slide_name)
                slide_tree = ET.fromstring(slide_xml)

                text_objects: list[TextObject] = []
                image_objects: list[ImageObject] = []

                # Include any master text objects for candidate matching
                for m_txt, m_bbox, m_rot in master_text_objects:
                    text_objects.append(
                        TextObject(
                            text=m_txt,
                            page=slide_index,
                            bbox=m_bbox,
                            font="Arial",
                            size=14.0,
                            rotation_degrees=m_rot,
                        )
                    )

                # Extract slide shapes
                for sp in slide_tree.findall(".//p:sp", NAMESPACES):
                    txt = _extract_shape_text(sp)
                    if txt:
                        bbox, rot = _parse_shape_transform(sp)
                        text_objects.append(
                            TextObject(
                                text=txt,
                                page=slide_index,
                                bbox=bbox,
                                font="Calibri",
                                size=16.0,
                                rotation_degrees=rot,
                            )
                        )

                # Extract pictures (<p:pic>)
                for pic_idx, pic in enumerate(slide_tree.findall(".//p:pic", NAMESPACES), start=1):
                    bbox, _ = _parse_shape_transform(pic)
                    w = max(int(bbox[2] - bbox[0]), 1)
                    h = max(int(bbox[3] - bbox[1]), 1)
                    pic_area = w * h
                    slide_area = max(slide_width * slide_height, 1.0)
                    coverage = min(pic_area / slide_area, 1.0)

                    image_objects.append(
                        ImageObject(
                            page=slide_index,
                            xref=pic_idx * 100 + slide_index,
                            bbox=bbox,
                            width=w,
                            height=h,
                            has_alpha=True,
                            coverage_ratio=round(coverage, 3),
                        )
                    )

                # Extract layout and master shapes (e.g. Gamma badge, template watermarks)
                for lm_tree, _, lm_hlink_map, _ in _get_layout_and_master_trees(zf, slide_name):
                    for lm_sp in lm_tree.findall(".//p:sp", NAMESPACES):
                        lm_txt = _extract_shape_text(lm_sp)
                        if lm_txt:
                            bbox, rot = _parse_shape_transform(lm_sp)
                            text_objects.append(
                                TextObject(
                                    text=lm_txt,
                                    page=slide_index,
                                    bbox=bbox,
                                    font="Arial",
                                    size=14.0,
                                    rotation_degrees=rot,
                                )
                            )

                    for lm_idx, lm_pic in enumerate(lm_tree.findall(".//p:pic", NAMESPACES), start=1):
                        bbox, _ = _parse_shape_transform(lm_pic)
                        w = max(int(bbox[2] - bbox[0]), 1)
                        h = max(int(bbox[3] - bbox[1]), 1)
                        pic_area = w * h
                        slide_area = max(slide_width * slide_height, 1.0)
                        coverage = min(pic_area / slide_area, 1.0)

                        image_objects.append(
                            ImageObject(
                                page=slide_index,
                                xref=80000 + lm_idx,
                                bbox=bbox,
                                width=w,
                                height=h,
                                has_alpha=True,
                                coverage_ratio=round(coverage, 3),
                            )
                        )

                        hlink = lm_pic.find(".//a:hlinkClick", NAMESPACES)
                        hlink_id = hlink.get(f"{{{NS_R}}}id") if hlink is not None else None
                        hlink_url = lm_hlink_map.get(hlink_id, "") if hlink_id else ""
                        if any(k in hlink_url.lower() for k in ("gamma.app", "canva.com", "tome.app")):
                            text_objects.append(
                                TextObject(
                                    text="Made with Gamma",
                                    page=slide_index,
                                    bbox=bbox,
                                    font="Arial",
                                    size=12.0,
                                    rotation_degrees=0.0,
                                )
                            )

                extractable_length = sum(len(t.text) for t in text_objects)
                total_text_objects += len(text_objects)
                total_images += len(image_objects)

                pages.append(
                    PageAnalysis(
                        page_number=slide_index,
                        width=round(slide_width, 2),
                        height=round(slide_height, 2),
                        is_scanned=False,
                        extractable_text_length=extractable_length,
                        text_object_count=len(text_objects),
                        image_count=len(image_objects),
                        text_objects=text_objects,
                        images=image_objects,
                    )
                )

            return DocumentAnalysisResponse(
                document_id=document_id,
                page_count=len(pages),
                total_text_objects=total_text_objects,
                total_images=total_images,
                appears_scanned=False,
                pages=pages,
                total_scanned=len(pages),
                failed_pages=[],
            )
    except PptxProcessingError:
        raise
    except Exception as exc:
        logger.error("analyze_pptx_failed: %s", exc, exc_info=True)
        raise PptxProcessingError("ANALYSIS_FAILED", f"Could not analyze presentation: {exc}") from exc


def remove_pptx_watermarks(
    source_path: Path,
    selected_candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[bytes, list[int], list[str]]:
    """
    Remove selected watermark candidates from PPTX slides, slide masters, and layouts.
    Returns (cleaned_bytes, pages_affected, skipped_ids).
    """
    if not selected_candidates:
        return source_path.read_bytes(), [], []

    selected_text_targets = {
        c.candidate_id: c.text.strip().lower() for c in selected_candidates if c.type == "text"
    }
    pages_affected_set: set[int] = set()
    skipped_ids: list[str] = []

    try:
        in_buf = io.BytesIO(source_path.read_bytes())
        out_buf = io.BytesIO()

        with zipfile.ZipFile(in_buf, "r") as src_zf, zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            slide_width, slide_height = _extract_slide_size(src_zf)
            slide_entries: list[tuple[int, str]] = []
            for name in src_zf.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))
            slide_entries.sort(key=lambda item: item[0])
            all_slide_indexes = set(range(1, len(slide_entries) + 1))
            shared_parts_are_in_scope = (
                pages_filter is None or all_slide_indexes.issubset(pages_filter)
            )

            # Process Master and Layout slides (e.g. Gamma or DRAFT master watermarks)
            for item_name in src_zf.namelist():
                if re.match(r"^ppt/(slideMasters|slideLayouts)/(slideMaster|slideLayout)\d+\.xml$", item_name):
                    if not shared_parts_are_in_scope:
                        try:
                            tree = ET.fromstring(src_zf.read(item_name))
                            sp_tree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                            if sp_tree is not None:
                                for shape in sp_tree.findall("p:sp", NAMESPACES):
                                    text = _extract_shape_text(shape).strip().lower()
                                    skipped_ids.extend(
                                        candidate_id
                                        for candidate_id, candidate_text in selected_text_targets.items()
                                        if candidate_text and (candidate_text in text or text in candidate_text)
                                    )
                        except ET.ParseError as exc:
                            logger.warning("pptx_shared_part_parse_failed part=%s: %s", item_name, exc)
                        dst_zf.writestr(item_name, src_zf.read(item_name))
                        continue

                    master_xml = src_zf.read(item_name)
                    try:
                        tree = ET.fromstring(master_xml)
                        spTree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                        modified = False
                        if spTree is not None:
                            # 1. Text shapes in layout/master
                            for sp in list(spTree.findall("p:sp", NAMESPACES)):
                                txt = _extract_shape_text(sp).strip().lower()
                                if any(t in txt or txt in t for t in selected_text_targets.values() if t):
                                    spTree.remove(sp)
                                    modified = True

                            # 2. Picture shapes in layout/master (e.g. Gamma badge, corner badge logos)
                            base_name = os.path.basename(item_name)
                            folder = item_name.split("/")[1]
                            rel_path = f"ppt/{folder}/_rels/{base_name}.rels"
                            rel_xml = ""
                            if rel_path in src_zf.namelist():
                                rel_xml = src_zf.read(rel_path).decode("utf-8", errors="ignore").lower()

                            gamma_selected = any("gamma" in c.text.lower() for c in selected_candidates)
                            ai_badge_in_rel = any(k in rel_xml for k in ("gamma.app", "canva.com", "tome.app"))

                            for pic in list(spTree.findall("p:pic", NAMESPACES)):
                                bbox, _ = _parse_shape_transform(pic)
                                pic_w = bbox[2] - bbox[0]
                                pic_h = bbox[3] - bbox[1]

                                matched = False
                                for cand in selected_candidates:
                                    dx = abs(bbox[0] - cand.bbox[0])
                                    dy = abs(bbox[1] - cand.bbox[1])
                                    if dx < 25 and dy < 25:
                                        matched = True
                                        break

                                if not matched and (gamma_selected or ai_badge_in_rel):
                                    matched = True

                                if not matched:
                                    is_corner_badge = (
                                        (pic_w * pic_h) < (slide_width * slide_height * 0.05)
                                        and (bbox[3] / slide_height >= 0.75)
                                        and (bbox[0] / slide_width <= 0.35 or bbox[2] / slide_width >= 0.65)
                                    )
                                    if is_corner_badge and any(
                                        any(term in cand.text.lower() for term in ("camscanner", "adobe scan", "clearscanner", "scanner", "gamma"))
                                        for cand in selected_candidates
                                    ):
                                        matched = True

                                if matched:
                                    spTree.remove(pic)
                                    modified = True
                        if modified:
                            dst_zf.writestr(item_name, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
                            for idx, _ in enumerate(slide_entries, start=1):
                                pages_affected_set.add(idx)
                            continue
                    except Exception as e:
                        logger.warning("Error processing master %s: %s", item_name, e)

                # Process slide files
                m_slide = re.match(r"^ppt/slides/slide(\d+)\.xml$", item_name)
                if m_slide:
                    # Find logical slide index (1-based)
                    slide_index = 1
                    for idx, (_, s_name) in enumerate(slide_entries, start=1):
                        if s_name == item_name:
                            slide_index = idx
                            break

                    if progress_callback is not None:
                        progress_callback(
                            slide_index,
                            len(slide_entries),
                            f"Removing PowerPoint watermarks — slide {slide_index} of {len(slide_entries)}",
                        )

                    if pages_filter is not None and slide_index not in pages_filter:
                        dst_zf.writestr(item_name, src_zf.read(item_name))
                        continue

                    slide_xml = src_zf.read(item_name)
                    tree = ET.fromstring(slide_xml)
                    spTree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                    slide_modified = False

                    if spTree is not None:
                        # Check text shapes
                        for sp in list(spTree.findall("p:sp", NAMESPACES)):
                            txt = _extract_shape_text(sp).strip().lower()
                            if not txt:
                                continue
                            for cand in selected_candidates:
                                if cand.type == "text":
                                    cand_text = cand.text.strip().lower()
                                    if cand_text in txt or txt in cand_text:
                                        spTree.remove(sp)
                                        slide_modified = True
                                        pages_affected_set.add(slide_index)
                                        break

                        # Check picture shapes
                        scanner_text_removed = any(
                            any(term in cand.text.lower() for term in ("camscanner", "scanned with", "adobe scan"))
                            for cand in selected_candidates
                            if cand.type == "text"
                        )
                        for pic in list(spTree.findall("p:pic", NAMESPACES)):
                            bbox, _ = _parse_shape_transform(pic)
                            pic_w = bbox[2] - bbox[0]
                            pic_h = bbox[3] - bbox[1]

                            # Check if explicitly selected
                            matched = False
                            for cand in selected_candidates:
                                if cand.type == "image":
                                    c_bbox = cand.bbox
                                    dx = abs(bbox[0] - c_bbox[0])
                                    dy = abs(bbox[1] - c_bbox[1])
                                    if dx < 15 and dy < 15:
                                        matched = True
                                        break

                            # Or if scanner text watermark was selected and this is a small corner logo
                            if not matched and scanner_text_removed:
                                is_corner_logo = (
                                    (pic_w * pic_h) < (slide_width * slide_height * 0.05)
                                    and (bbox[3] / slide_height >= 0.75)
                                    and (bbox[0] / slide_width <= 0.35 or bbox[2] / slide_width >= 0.65)
                                )
                                if is_corner_logo:
                                    matched = True

                            if matched:
                                spTree.remove(pic)
                                slide_modified = True
                                pages_affected_set.add(slide_index)

                    if slide_modified:
                        dst_zf.writestr(item_name, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
                    else:
                        dst_zf.writestr(item_name, slide_xml)
                else:
                    # Non-slide file: copy verbatim
                    dst_zf.writestr(item_name, src_zf.read(item_name))

        cleaned_bytes = out_buf.getvalue()
        pages_affected = sorted(pages_affected_set)
        return cleaned_bytes, pages_affected, sorted(set(skipped_ids))

    except Exception as exc:
        logger.error("remove_pptx_watermarks failed: %s", exc, exc_info=True)
        raise PptxProcessingError("REMOVAL_FAILED", f"Failed to clean PPTX presentation: {exc}") from exc


def remove_pptx_manual_regions(
    source_path: Path,
    regions: list[ManualRegion],
    apply_to_all_pages: bool,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[bytes, list[int]]:
    """
    Remove shapes (text blocks, picture watermarks, stamps) intersecting manually
    selected regions from a PowerPoint presentation.
    Preserves all slide order, dimensions, layout, images, and text outside the selected area.
    """
    if not regions:
        return source_path.read_bytes(), []

    pages_affected_set: set[int] = set()

    try:
        in_buf = io.BytesIO(source_path.read_bytes())
        out_buf = io.BytesIO()

        with zipfile.ZipFile(in_buf, "r") as src_zf, zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            slide_width, slide_height = _extract_slide_size(src_zf)

            slide_entries: list[tuple[int, str]] = []
            for name in src_zf.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))
            slide_entries.sort(key=lambda item: item[0])

            total_slides = max(len(slide_entries), 1)
            all_slide_indexes = set(range(1, len(slide_entries) + 1))
            shared_parts_are_in_scope = (
                apply_to_all_pages
                or all_slide_indexes.issubset({region.page for region in regions})
            )

            # Map regions by slide index (1-based)
            regions_by_slide: dict[int, list[ManualRegion]] = defaultdict(list)
            if apply_to_all_pages:
                ref_region = regions[0]
                for s_idx in range(1, total_slides + 1):
                    for r in regions:
                        if r.page == ref_region.page:
                            regions_by_slide[s_idx].append(r)
            else:
                for r in regions:
                    if 1 <= r.page <= total_slides:
                        regions_by_slide[r.page].append(r)

            for idx, (_, slide_name) in enumerate(slide_entries, start=1):
                if progress_callback is not None:
                    progress_callback(
                        idx,
                        total_slides,
                        f"Applying manual removal — slide {idx} of {total_slides}",
                    )

                slide_xml = src_zf.read(slide_name)
                slide_regions = regions_by_slide.get(idx, [])

                if not slide_regions:
                    dst_zf.writestr(slide_name, slide_xml)
                    continue

                tree = ET.fromstring(slide_xml)
                spTree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                slide_modified = False

                if spTree is not None:
                    # Convert manual regions to point boxes
                    sel_boxes = [
                        (
                            r.x0 * slide_width,
                            r.y0 * slide_height,
                            r.x1 * slide_width,
                            r.y1 * slide_height,
                        )
                        for r in slide_regions
                    ]

                    # 1. Inspect text shapes (<p:sp>)
                    for sp in list(spTree.findall("p:sp", NAMESPACES)):
                        bbox, _ = _parse_shape_transform(sp)
                        sp_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1.0)
                        sp_cx = (bbox[0] + bbox[2]) / 2
                        sp_cy = (bbox[1] + bbox[3]) / 2

                        for sx0, sy0, sx1, sy1 in sel_boxes:
                            ix0, iy0 = max(bbox[0], sx0), max(bbox[1], sy0)
                            ix1, iy1 = min(bbox[2], sx1), min(bbox[3], sy1)
                            if ix1 > ix0 and iy1 > iy0:
                                inter_area = (ix1 - ix0) * (iy1 - iy0)
                                if (inter_area / sp_area >= 0.35) or (sx0 <= sp_cx <= sx1 and sy0 <= sp_cy <= sy1):
                                    spTree.remove(sp)
                                    slide_modified = True
                                    pages_affected_set.add(idx)
                                    break

                    # 2. Inspect picture shapes (<p:pic>)
                    for pic in list(spTree.findall("p:pic", NAMESPACES)):
                        bbox, _ = _parse_shape_transform(pic)
                        pic_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1.0)
                        pic_cx = (bbox[0] + bbox[2]) / 2
                        pic_cy = (bbox[1] + bbox[3]) / 2

                        for sx0, sy0, sx1, sy1 in sel_boxes:
                            ix0, iy0 = max(bbox[0], sx0), max(bbox[1], sy0)
                            ix1, iy1 = min(bbox[2], sx1), min(bbox[3], sy1)
                            if ix1 > ix0 and iy1 > iy0:
                                inter_area = (ix1 - ix0) * (iy1 - iy0)
                                if (inter_area / pic_area >= 0.35) or (sx0 <= pic_cx <= sx1 and sy0 <= pic_cy <= sy1):
                                    spTree.remove(pic)
                                    slide_modified = True
                                    pages_affected_set.add(idx)
                                    break

                if slide_modified:
                    dst_zf.writestr(slide_name, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
                else:
                    dst_zf.writestr(slide_name, slide_xml)

            # Process non-slide files (check slideMasters and slideLayouts for intersecting shapes)
            slide_set = {s[1] for s in slide_entries}
            if not shared_parts_are_in_scope:
                all_sel_boxes = []
            else:
                all_sel_boxes = [
                    (
                        r.x0 * slide_width,
                        r.y0 * slide_height,
                        r.x1 * slide_width,
                        r.y1 * slide_height,
                    )
                    for r in regions
                ]

            for item_name in src_zf.namelist():
                if item_name in slide_set:
                    continue

                if re.match(r"^ppt/(slideMasters|slideLayouts)/(slideMaster|slideLayout)\d+\.xml$", item_name):
                    try:
                        lm_xml = src_zf.read(item_name)
                        tree = ET.fromstring(lm_xml)
                        spTree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                        lm_modified = False
                        if spTree is not None:
                            for shape in list(spTree.findall("p:sp", NAMESPACES)) + list(spTree.findall("p:pic", NAMESPACES)):
                                bbox, _ = _parse_shape_transform(shape)
                                sh_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1.0)
                                sh_cx = (bbox[0] + bbox[2]) / 2
                                sh_cy = (bbox[1] + bbox[3]) / 2

                                for sx0, sy0, sx1, sy1 in all_sel_boxes:
                                    ix0, iy0 = max(bbox[0], sx0), max(bbox[1], sy0)
                                    ix1, iy1 = min(bbox[2], sx1), min(bbox[3], sy1)
                                    if ix1 > ix0 and iy1 > iy0:
                                        inter_area = (ix1 - ix0) * (iy1 - iy0)
                                        if (inter_area / sh_area >= 0.25) or (sx0 <= sh_cx <= sx1 and sy0 <= sh_cy <= sy1):
                                            spTree.remove(shape)
                                            lm_modified = True
                                            for idx, _ in enumerate(slide_entries, start=1):
                                                pages_affected_set.add(idx)
                                            break

                        if lm_modified:
                            dst_zf.writestr(item_name, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
                            continue
                    except Exception as e:
                        logger.warning("Error processing layout/master in manual removal %s: %s", item_name, e)

                dst_zf.writestr(item_name, src_zf.read(item_name))

        cleaned_bytes = out_buf.getvalue()
        return cleaned_bytes, sorted(pages_affected_set)

    except Exception as exc:
        logger.error("remove_pptx_manual_regions failed: %s", exc, exc_info=True)
        raise PptxProcessingError("MANUAL_REMOVAL_FAILED", f"Failed to remove manual selection from presentation: {exc}") from exc


def _get_font(
    font_name: str,
    size_pt: float,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font for rendering text at actual scale, with fallbacks."""
    size_px = max(9, int(round(size_pt)))
    font_candidates: list[str] = []

    clean_name = font_name.strip().lower()
    if "calibri" in clean_name:
        font_candidates.extend(["calibrib.ttf" if bold else "calibri.ttf", "arialbd.ttf" if bold else "arial.ttf"])
    elif "arial" in clean_name:
        font_candidates.extend(["arialbd.ttf" if bold else "arial.ttf", "calibrib.ttf" if bold else "calibri.ttf"])
    elif "segoe" in clean_name:
        font_candidates.extend(["segoeuib.ttf" if bold else "segoeui.ttf", "calibri.ttf"])
    elif "times" in clean_name or "roman" in clean_name:
        font_candidates.extend(["timesbd.ttf" if bold else "times.ttf", "arial.ttf"])
    else:
        if bold:
            font_candidates.extend(["arialbd.ttf", "calibrib.ttf", "segoeuib.ttf"])
        else:
            font_candidates.extend(["calibri.ttf", "arial.ttf", "segoeui.ttf"])

    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size_px)
        except Exception:
            continue

    return ImageFont.load_default()


def _parse_color(clr_elem: ET.Element | None, default: tuple[int, int, int] = (40, 44, 52)) -> tuple[int, int, int]:
    """Parse color from OpenXML color elements (<a:srgbClr> or <a:schemeClr>)."""
    if clr_elem is None:
        return default
    srgb = clr_elem.find(".//a:srgbClr", NAMESPACES)
    if srgb is not None:
        val = srgb.get("val", "")
        if len(val) == 6:
            try:
                return (int(val[0:2], 16), int(val[2:4], 16), int(val[4:6], 16))
            except ValueError:
                pass
    return default


def _wrap_text_to_width(
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Wrap a line of text so that it fits within max_width pixels."""
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_w = bbox[2] - bbox[0]
        except Exception:
            line_w = len(test_line) * 8

        if line_w <= max_width or not current_line:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)
    return lines


def render_pptx_slide_preview(source_path: Path, slide_number: int) -> bytes:
    """
    Render a slide preview as a high-quality JPEG image.
    Accurately extracts slide text with actual font sizes, typography,
    embedded pictures (<p:pic>), shape dimensions, and layout coordinates.
    """
    try:
        with zipfile.ZipFile(source_path, "r") as zf:
            slide_width, slide_height = _extract_slide_size(zf)

            slide_entries: list[tuple[int, str]] = []
            for name in zf.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))
            slide_entries.sort(key=lambda item: item[0])

            if slide_number < 1 or slide_number > len(slide_entries):
                raise PptxProcessingError(
                    "INVALID_PAGE",
                    f"This presentation has {len(slide_entries)} slides.",
                )

            slide_name = slide_entries[slide_number - 1][1]
            slide_xml = zf.read(slide_name)
            slide_tree = ET.fromstring(slide_xml)

            # Target canvas: 120 DPI rendering
            # Standard pt is 72 pt/in, scale = 120 / 72 = 1.6667
            scale = 120.0 / 72.0
            canvas_w = int(slide_width * scale)
            canvas_h = int(slide_height * scale)

            img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
            draw = ImageDraw.Draw(img)

            # Parse slide relationships to locate embedded media files (images/logos)
            rel_map: dict[str, str] = {}
            slide_base = os.path.basename(slide_name)
            slide_rel_path = f"ppt/slides/_rels/{slide_base}.rels"
            if slide_rel_path in zf.namelist():
                try:
                    rel_tree = ET.fromstring(zf.read(slide_rel_path))
                    for rel in rel_tree.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                        r_id = rel.get("Id")
                        if not r_id:
                            continue
                        target = rel.get("Target", "")
                        if target.startswith("../media/"):
                            rel_map[r_id] = "ppt/media/" + target[len("../media/"):]
                        elif target.startswith("media/"):
                            rel_map[r_id] = "ppt/" + target
                except Exception as exc:
                    logger.debug("parse_slide_rels_error: %s", exc)

            # 0. Render background pictures from slide layout & master (e.g. Gamma badge, template watermarks)
            for lm_tree, lm_rel_map, _, _ in _get_layout_and_master_trees(zf, slide_name):
                for pic in lm_tree.findall(".//p:pic", NAMESPACES):
                    try:
                        blip = pic.find(".//a:blip", NAMESPACES)
                        if blip is None:
                            continue
                        embed_id = blip.get(f"{{{NS_R}}}embed") or blip.get("r:embed")
                        if not embed_id or embed_id not in lm_rel_map:
                            continue
                        media_path = lm_rel_map[embed_id]
                        if media_path not in zf.namelist():
                            continue

                        pic_data = zf.read(media_path)
                        pic_img = Image.open(io.BytesIO(pic_data))

                        bbox, _ = _parse_shape_transform(pic)
                        px0 = max(0, int(bbox[0] * scale))
                        py0 = max(0, int(bbox[1] * scale))
                        pw = max(4, int((bbox[2] - bbox[0]) * scale))
                        ph = max(4, int((bbox[3] - bbox[1]) * scale))

                        resized = pic_img.resize((pw, ph), Image.Resampling.LANCZOS)
                        if resized.mode == "RGBA":
                            img.paste(resized, (px0, py0), resized)
                        else:
                            img.paste(resized, (px0, py0))
                    except Exception as lm_exc:
                        logger.debug("render_lm_pic_failed: %s", lm_exc)

            # 1. Render embedded pictures (<p:pic>)
            for pic in slide_tree.findall(".//p:pic", NAMESPACES):
                try:
                    blip = pic.find(".//a:blip", NAMESPACES)
                    if blip is None:
                        continue
                    embed_id = blip.get(f"{{{NS_R}}}embed") or blip.get("r:embed")
                    if not embed_id or embed_id not in rel_map:
                        continue
                    media_path = rel_map[embed_id]
                    if media_path not in zf.namelist():
                        continue

                    pic_data = zf.read(media_path)
                    pic_img = Image.open(io.BytesIO(pic_data))

                    bbox, _ = _parse_shape_transform(pic)
                    px0 = max(0, int(bbox[0] * scale))
                    py0 = max(0, int(bbox[1] * scale))
                    pw = max(4, int((bbox[2] - bbox[0]) * scale))
                    ph = max(4, int((bbox[3] - bbox[1]) * scale))

                    resized = pic_img.resize((pw, ph), Image.Resampling.LANCZOS)
                    if resized.mode == "RGBA":
                        img.paste(resized, (px0, py0), resized)
                    else:
                        img.paste(resized, (px0, py0))
                except Exception as pic_exc:
                    logger.debug("render_pic_failed: %s", pic_exc)

            # 2. Render text shapes (<p:sp>) with actual font sizes and wrapping
            for sp in slide_tree.findall(".//p:sp", NAMESPACES):
                txBody = sp.find(".//p:txBody", NAMESPACES)
                if txBody is None:
                    continue

                bbox, _ = _parse_shape_transform(sp)
                sx0 = int(bbox[0] * scale)
                sy0 = int(bbox[1] * scale)
                sx1 = int(bbox[2] * scale)
                sy1 = int(bbox[3] * scale)
                max_w = max(40, sx1 - sx0 - 8)

                # Determine default shape font size if runs omit sz
                shape_h_pt = bbox[3] - bbox[1]
                default_sz_pt = 22.0 if shape_h_pt > 70 and sy0 < int(canvas_h * 0.3) else 14.0

                cur_y = sy0 + 4
                for p in txBody.findall(".//a:p", NAMESPACES):
                    # Check paragraph default run properties
                    p_sz_pt = default_sz_pt
                    pPr = p.find("a:pPr", NAMESPACES)
                    if pPr is not None:
                        defRPr = pPr.find("a:defRPr", NAMESPACES)
                        if defRPr is not None and "sz" in defRPr.attrib:
                            try:
                                p_sz_pt = int(defRPr.attrib["sz"]) / 100.0
                            except (ValueError, TypeError):
                                pass

                    runs = p.findall("a:r", NAMESPACES)
                    if not runs:
                        # Paragraph without <a:r>, could have <a:t> directly or empty line
                        t_direct = p.find("a:t", NAMESPACES)
                        if t_direct is not None and t_direct.text:
                            text_str = t_direct.text.strip()
                            font = _get_font("calibri", p_sz_pt * scale, bold=False)
                            wrapped_lines = _wrap_text_to_width(text_str, font, max_w, draw)
                            line_h = int(p_sz_pt * scale * 1.25)
                            for w_line in wrapped_lines:
                                if cur_y > sy1 + 10:
                                    break
                                draw.text((sx0 + 4, cur_y), w_line, font=font, fill=(40, 44, 52))
                                cur_y += line_h
                            cur_y += int(line_h * 0.2)
                        continue

                    for r in runs:
                        t_elem = r.find("a:t", NAMESPACES)
                        if t_elem is None or not t_elem.text or not t_elem.text.strip():
                            continue
                        run_text = t_elem.text.strip()

                        # Extract run properties: font size, bold, typeface, color
                        rPr = r.find("a:rPr", NAMESPACES)
                        run_sz_pt = p_sz_pt
                        is_bold = False
                        typeface = "calibri"
                        text_color = (40, 44, 52)

                        if rPr is not None:
                            if "sz" in rPr.attrib:
                                try:
                                    run_sz_pt = int(rPr.attrib["sz"]) / 100.0
                                except (ValueError, TypeError):
                                    pass
                            if rPr.attrib.get("b") in ("1", "true"):
                                is_bold = True
                            latin = rPr.find("a:latin", NAMESPACES)
                            if latin is not None and latin.attrib.get("typeface"):
                                typeface = latin.attrib["typeface"]
                            text_color = _parse_color(rPr, default=(40, 44, 52))

                        font_size_px = max(11, int(round(run_sz_pt * scale)))
                        font = _get_font(typeface, font_size_px, bold=is_bold)
                        line_h = max(font_size_px + 4, int(font_size_px * 1.25))

                        wrapped_lines = _wrap_text_to_width(run_text, font, max_w, draw)
                        for w_line in wrapped_lines:
                            if cur_y > sy1 + 15:
                                break
                            draw.text((sx0 + 4, cur_y), w_line, font=font, fill=text_color)
                            cur_y += line_h

                    # Paragraph spacing
                    cur_y += 4

            # Subtle page border
            draw.rectangle([0, 0, canvas_w - 1, canvas_h - 1], outline=(220, 225, 230), width=1)

            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=90)
            return out_io.getvalue()

    except PptxProcessingError:
        raise
    except Exception as exc:
        logger.warning("render_pptx_slide_preview fallback: %s", exc)
        img = Image.new("RGB", (1280, 720), (248, 250, 252))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 1260, 700], fill=(255, 255, 255), outline=(200, 210, 220), width=2)
        default_font = _get_font("arial", 24, bold=True)
        draw.text((60, 60), f"PowerPoint Slide {slide_number}", font=default_font, fill=(30, 41, 59))
        draw.text((60, 110), "Preview generated", font=_get_font("arial", 16), fill=(100, 116, 139))
        out_io = io.BytesIO()
        img.save(out_io, format="JPEG", quality=85)
        return out_io.getvalue()
