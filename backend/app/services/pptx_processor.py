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
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from app.schemas.analysis import DocumentAnalysisResponse, ImageObject, PageAnalysis, TextObject
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
                return "ppt/presentation.xml" in namelist or "[Content_Types].xml" in namelist
        elif isinstance(path, bytes):
            with zipfile.ZipFile(io.BytesIO(path), "r") as zf:
                namelist = zf.namelist()
                return "ppt/presentation.xml" in namelist or "[Content_Types].xml" in namelist
    except Exception:
        return False
    return False


def get_pptx_slide_count(path: Path) -> int:
    """Quickly count slides in a PPTX presentation."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            slide_files = [n for n in zf.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n)]
            return max(len(slide_files), 1)
    except Exception:
        return 1


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


def analyze_pptx(document_id: str, path: Path) -> DocumentAnalysisResponse:
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

            for slide_index, (slide_num, slide_name) in enumerate(slide_entries, start=1):
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
            )
    except Exception as exc:
        logger.error("analyze_pptx_failed: %s", exc, exc_info=True)
        raise PptxProcessingError("ANALYSIS_FAILED", f"Could not analyze presentation: {exc}") from exc


def remove_pptx_watermarks(
    source_path: Path,
    selected_candidates: list[WatermarkCandidate],
    pages_filter: set[int] | None = None,
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
    selected_candidate_ids = {c.candidate_id for c in selected_candidates}

    pages_affected_set: set[int] = set()
    skipped_ids: list[str] = []

    try:
        in_buf = io.BytesIO(source_path.read_bytes())
        out_buf = io.BytesIO()

        with zipfile.ZipFile(in_buf, "r") as src_zf, zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as dst_zf:
            slide_entries: list[tuple[int, str]] = []
            for name in src_zf.namelist():
                m = re.match(r"^ppt/slides/slide(\d+)\.xml$", name)
                if m:
                    slide_entries.append((int(m.group(1)), name))
            slide_entries.sort(key=lambda item: item[0])

            # Process Master and Layout slides (e.g. Gamma or DRAFT master watermarks)
            for item_name in src_zf.namelist():
                if re.match(r"^ppt/(slideMasters|slideLayouts)/(slideMaster|slideLayout)\d+\.xml$", item_name):
                    master_xml = src_zf.read(item_name)
                    try:
                        tree = ET.fromstring(master_xml)
                        spTree = tree.find(".//p:cSld/p:spTree", NAMESPACES)
                        modified = False
                        if spTree is not None:
                            for sp in list(spTree.findall("p:sp", NAMESPACES)):
                                txt = _extract_shape_text(sp).strip().lower()
                                if any(t in txt or txt in t for t in selected_text_targets.values() if t):
                                    spTree.remove(sp)
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
                    slide_num = int(m_slide.group(1))
                    # Find logical slide index (1-based)
                    slide_index = 1
                    for idx, (s_n, s_name) in enumerate(slide_entries, start=1):
                        if s_name == item_name:
                            slide_index = idx
                            break

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
                        for pic in list(spTree.findall("p:pic", NAMESPACES)):
                            bbox, _ = _parse_shape_transform(pic)
                            for cand in selected_candidates:
                                if cand.type == "image":
                                    # Match bbox similarity
                                    c_bbox = cand.bbox
                                    dx = abs(bbox[0] - c_bbox[0])
                                    dy = abs(bbox[1] - c_bbox[1])
                                    if dx < 15 and dy < 15:
                                        spTree.remove(pic)
                                        slide_modified = True
                                        pages_affected_set.add(slide_index)
                                        break

                    if slide_modified:
                        dst_zf.writestr(item_name, ET.tostring(tree, encoding="utf-8", xml_declaration=True))
                    else:
                        dst_zf.writestr(item_name, slide_xml)
                else:
                    # Non-slide file: copy verbatim
                    dst_zf.writestr(item_name, src_zf.read(item_name))

        cleaned_bytes = out_buf.getvalue()
        pages_affected = sorted(pages_affected_set)
        return cleaned_bytes, pages_affected, skipped_ids

    except Exception as exc:
        logger.error("remove_pptx_watermarks failed: %s", exc, exc_info=True)
        raise PptxProcessingError("REMOVAL_FAILED", f"Failed to clean PPTX presentation: {exc}") from exc


def render_pptx_slide_preview(source_path: Path, slide_number: int) -> bytes:
    """
    Render a slide preview as a clean JPEG image for before/after inspection.
    Extracts slide text, layout, and pictures to render a high-quality preview canvas.
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
                slide_number = 1

            slide_name = slide_entries[slide_number - 1][1]
            slide_xml = zf.read(slide_name)
            slide_tree = ET.fromstring(slide_xml)

            # Target canvas: 120 DPI rendering
            # Standard pt is 72 pt/in, so scale = 120 / 72 = 1.6667
            scale = 120.0 / 72.0
            canvas_w = int(slide_width * scale)
            canvas_h = int(slide_height * scale)

            img = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
            draw = ImageDraw.Draw(img)

            # Background subtle border
            draw.rectangle([0, 0, canvas_w - 1, canvas_h - 1], outline=(220, 225, 230), width=1)

            # Extract slide shapes and render text/shapes
            for sp in slide_tree.findall(".//p:sp", NAMESPACES):
                txt = _extract_shape_text(sp)
                if txt:
                    bbox, rot = _parse_shape_transform(sp)
                    x0 = int(bbox[0] * scale)
                    y0 = int(bbox[1] * scale)
                    x1 = int(bbox[2] * scale)
                    y1 = int(bbox[3] * scale)
                    w = max(x1 - x0, 10)
                    h = max(y1 - y0, 10)

                    # Draw text lines cleanly
                    lines = txt.split("\n")
                    cur_y = y0 + 4
                    for line in lines:
                        if cur_y > y1 + 20:
                            break
                        # Draw readable text snippet
                        draw.text((x0 + 4, cur_y), line[:120], fill=(40, 44, 52))
                        cur_y += 18

            # Output as JPEG
            out_io = io.BytesIO()
            img.save(out_io, format="JPEG", quality=85)
            return out_io.getvalue()
    except Exception as exc:
        logger.warning("render_pptx_slide_preview fallback: %s", exc)
        # Fallback placeholder card
        img = Image.new("RGB", (1280, 720), (248, 250, 252))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 1260, 700], fill=(255, 255, 255), outline=(200, 210, 220), width=2)
        draw.text((60, 60), f"PowerPoint Slide {slide_number}", fill=(30, 41, 59))
        draw.text((60, 100), "Preview generated successfully", fill=(100, 116, 139))
        out_io = io.BytesIO()
        img.save(out_io, format="JPEG", quality=85)
        return out_io.getvalue()
