"""
Tests for PowerPoint (.pptx) watermark detection and removal, and the expanded
tokenless heuristic watermark knowledge base (CamScanner, Gamma, Canva, etc.).
"""
from __future__ import annotations

from pathlib import Path
import io
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from fastapi.testclient import TestClient

import pymupdf as fitz

from app.main import app
from app.schemas.analysis import DocumentAnalysisResponse, PageAnalysis, TextObject
from app.schemas.manual import ManualRegion
from app.schemas.watermark import WatermarkCandidate
from app.services.pptx_processor import (
    remove_pptx_manual_regions,
    remove_pptx_watermarks,
    render_pptx_slide_preview,
)
from app.services.watermark_detector import generate_candidates

client = TestClient(app)


def _build_test_pptx(watermark_text: str = "Made with Gamma", title_text: str = "Quarterly Business Review") -> bytes:
    """Build a minimal valid .pptx file with slides, shapes, and watermark."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>\n'
            '  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'
            '  <Override PartName="/ppt/slides/slide2.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>\n'
            '</Types>'
        )
        zf.writestr("[Content_Types].xml", content_types)

        # _rels/.rels
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>\n'
            '</Relationships>'
        )
        zf.writestr("_rels/.rels", root_rels)

        # ppt/presentation.xml
        presentation_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
            '  <p:sldSz cx="12192000" cy="6858000"/>\n'
            '  <p:sldIdLst>\n'
            '    <p:sldId id="256" r:id="rId1"/>\n'
            '    <p:sldId id="257" r:id="rId2"/>\n'
            '  </p:sldIdLst>\n'
            '</p:presentation>'
        )
        zf.writestr("ppt/presentation.xml", presentation_xml)

        # Helper to generate slide xml
        def make_slide_xml(slide_title: str) -> str:
            return (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">\n'
                '  <p:cSld>\n'
                '    <p:spTree>\n'
                '      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:grpSpPr/></p:nvGrpSpPr>\n'
                '      <p:grpSpPr/>\n'
                '      <!-- Main Title Shape -->\n'
                '      <p:sp>\n'
                '        <p:nvSpPr><p:cNvPr id="2" name="Title 1"/></p:nvSpPr>\n'
                '        <p:spPr><a:xfrm><a:off x="1000000" y="1000000"/><a:ext cx="8000000" cy="1500000"/></a:xfrm></p:spPr>\n'
                '        <p:txBody><a:bodyPr/><a:p><a:r><a:t>' + slide_title + '</a:t></a:r></a:p></p:txBody>\n'
                '      </p:sp>\n'
                '      <!-- Watermark Shape (e.g. Made with Gamma or Scanned with CamScanner) -->\n'
                '      <p:sp>\n'
                '        <p:nvSpPr><p:cNvPr id="3" name="Watermark"/></p:nvSpPr>\n'
                '        <p:spPr><a:xfrm><a:off x="1000000" y="6000000"/><a:ext cx="4000000" cy="500000"/></a:xfrm></p:spPr>\n'
                '        <p:txBody><a:bodyPr/><a:p><a:r><a:t>' + watermark_text + '</a:t></a:r></a:p></p:txBody>\n'
                '      </p:sp>\n'
                '    </p:spTree>\n'
                '  </p:cSld>\n'
                '</p:sld>'
            )

        zf.writestr("ppt/slides/slide1.xml", make_slide_xml(title_text))
        zf.writestr("ppt/slides/slide2.xml", make_slide_xml("Slide 2 Key Findings"))

    return buf.getvalue()


def _add_shared_layout(
    pptx_bytes: bytes,
    watermark_text: str = "Made with Gamma",
    include_corner_image: bool = False,
) -> bytes:
    """Add a layout watermark referenced by both test slides."""
    corner_image = (
        '<p:pic><p:spPr><a:xfrm><a:off x="11000000" y="6500000"/>'
        '<a:ext cx="300000" cy="300000"/></a:xfrm></p:spPr></p:pic>'
        if include_corner_image
        else ""
    )
    layout_xml = (
        '<p:sldLayout xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><p:spTree><p:sp>'
        '<p:spPr><a:xfrm><a:off x="1000000" y="6000000"/>'
        '<a:ext cx="4000000" cy="500000"/></a:xfrm></p:spPr>'
        '<p:txBody><a:p><a:r><a:t>' + watermark_text + '</a:t></a:r></a:p></p:txBody>'
        '</p:sp>' + corner_image + '</p:spTree></p:cSld></p:sldLayout>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
        'Target="../slideLayouts/slideLayout1.xml"/>'
        '</Relationships>'
    )

    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(pptx_bytes), "r") as source, zipfile.ZipFile(
        result, "w", zipfile.ZIP_DEFLATED
    ) as destination:
        for name in source.namelist():
            content = source.read(name)
            if name in {"ppt/slides/slide1.xml", "ppt/slides/slide2.xml"}:
                slide = ET.fromstring(content)
                shape_tree = slide.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}spTree")
                if shape_tree is not None:
                    for shape in list(shape_tree):
                        shape_text = "".join(
                            text.text or ""
                            for text in shape.findall(
                                ".//{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                            )
                        )
                        if shape_text == watermark_text:
                            shape_tree.remove(shape)
                content = ET.tostring(slide, encoding="utf-8", xml_declaration=True)
            destination.writestr(name, content)
        destination.writestr("ppt/slideLayouts/slideLayout1.xml", layout_xml)
        destination.writestr("ppt/slides/_rels/slide1.xml.rels", relationships)
        destination.writestr("ppt/slides/_rels/slide2.xml.rels", relationships)
    return result.getvalue()


def _gamma_candidate() -> WatermarkCandidate:
    return WatermarkCandidate(
        candidate_id="shared-layout-gamma",
        type="text",
        text="Made with Gamma",
        page=1,
        bbox=(78.74, 472.44, 393.7, 511.81),
        rotation_degrees=0,
        confidence=0.95,
        reasons=["Recognized watermark text"],
    )


def test_pptx_upload_analyze_and_detect() -> None:
    """Test full upload -> analyze -> detect pipeline on a PPTX file."""
    pptx_bytes = _build_test_pptx(watermark_text="Made with Gamma")

    # 1. Upload
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("presentation.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    doc_id = data["document_id"]
    assert data["page_count"] == 2

    # 2. Analyze
    analyze_resp = client.post(f"/api/v1/documents/{doc_id}/analyze")
    assert analyze_resp.status_code == 200
    analyze_data = analyze_resp.json()
    assert analyze_data["page_count"] == 2
    assert analyze_data["total_text_objects"] >= 4

    # 3. Detect
    detect_resp = client.post(f"/api/v1/documents/{doc_id}/detect")
    assert detect_resp.status_code == 200
    detect_data = detect_resp.json()
    assert detect_data["candidate_count"] > 0
    
    # Confirm "Made with Gamma" is detected with high confidence
    gamma_candidates = [c for c in detect_data["candidates"] if "gamma" in c["text"].lower()]
    assert len(gamma_candidates) > 0
    assert gamma_candidates[0]["confidence"] >= 0.85


def test_pptx_watermark_removal_and_download() -> None:
    """Test removing detected watermarks from PPTX and downloading the clean file."""
    pptx_bytes = _build_test_pptx(watermark_text="Scanned with CamScanner", title_text="My Project Plan")

    upload_resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    doc_id = upload_resp.json()["document_id"]

    detect_resp = client.post(f"/api/v1/documents/{doc_id}/detect")
    candidates = detect_resp.json()["candidates"]
    candidate_ids = [c["candidate_id"] for c in candidates if "camscanner" in c["text"].lower()]
    assert len(candidate_ids) > 0

    # Process removal
    proc_resp = client.post(
        f"/api/v1/documents/{doc_id}/process",
        json={"candidate_ids": candidate_ids, "pages": "all"},
    )
    assert proc_resp.status_code == 200
    proc_data = proc_resp.json()
    assert proc_data["removed_count"] > 0

    # Download cleaned PPTX
    dl_resp = client.get(f"/api/v1/documents/{doc_id}/download")
    assert dl_resp.status_code == 200
    assert "cleaned_report.pptx" in dl_resp.headers.get("content-disposition", "")
    
    # Verify downloaded bytes are valid PPTX and watermark text is gone
    cleaned_zf = zipfile.ZipFile(io.BytesIO(dl_resp.content), "r")
    slide1_xml = cleaned_zf.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "Scanned with CamScanner" not in slide1_xml
    assert "My Project Plan" in slide1_xml


def test_expanded_watermark_knowledge_base_detection() -> None:
    """Test that all major document watermarks (CamScanner, Gamma, Canva, etc.) are detected."""
    test_cases = [
        "Made with Gamma",
        "gamma.app",
        "Scanned with CamScanner",
        "CS CamScanner",
        "Designed with Canva",
        "CONFIDENTIAL",
        "STRICTLY CONFIDENTIAL",
        "DRAFT",
        "SAMPLE",
        "DO NOT DISTRIBUTE",
        "Made with Tome",
        "DocuSign Envelope ID: 1234-ABCD",
        "Created with WPS Office",
        "ilovepdf.com",
    ]

    for wm_text in test_cases:
        dummy_analysis = DocumentAnalysisResponse(
            document_id="test-doc",
            page_count=1,
            total_text_objects=1,
            total_images=0,
            appears_scanned=False,
            pages=[
                PageAnalysis(
                    page_number=1,
                    width=612.0,
                    height=792.0,
                    is_scanned=False,
                    extractable_text_length=len(wm_text),
                    text_object_count=1,
                    image_count=0,
                    text_objects=[
                        TextObject(
                            text=wm_text,
                            page=1,
                            bbox=(100.0, 720.0, 400.0, 750.0),  # footer zone
                            font="Helvetica",
                            size=12.0,
                            rotation_degrees=0.0,
                        )
                    ],
                    images=[],
                )
            ],
        )
        candidates = generate_candidates(dummy_analysis)
        assert len(candidates) > 0, f"Failed to detect watermark: {wm_text}"
        assert candidates[0].confidence >= 0.85, f"Low confidence for {wm_text}: {candidates[0].confidence}"


def test_pptx_slide_preview() -> None:
    """Test generating a slide preview image for a PPTX document."""
    pptx_bytes = _build_test_pptx(watermark_text="CONFIDENTIAL", title_text="Slide Preview Test")
    upload_resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("slides.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    doc_id = upload_resp.json()["document_id"]

    preview_resp = client.get(f"/api/v1/documents/{doc_id}/preview/1")
    assert preview_resp.status_code == 200
    assert preview_resp.headers["content-type"] == "image/jpeg"
    assert len(preview_resp.content) > 100


def test_pptx_slide_preview_uses_office_conversion_cache(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "presentation.pptx"
    source_path.write_bytes(_build_test_pptx())
    cache_path = tmp_path / "presentation.preview.pdf"

    pdf = fitz.open()
    pdf.new_page(width=960, height=540)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    def fake_office_run(command: list[str], **_kwargs) -> SimpleNamespace:
        output_dir = Path(command[command.index("--outdir") + 1])
        (output_dir / "presentation.pdf").write_bytes(pdf_bytes)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("app.services.pptx_processor.shutil.which", lambda _name: "soffice")
    monkeypatch.setattr("app.services.pptx_processor.subprocess.run", fake_office_run)

    rendered = render_pptx_slide_preview(source_path, 1, cache_path)
    assert rendered.startswith(b"\xff\xd8\xff")
    assert cache_path.is_file()

    def unexpected_conversion(*_args, **_kwargs):
        raise AssertionError("Cached PDF should avoid a second Office conversion")

    monkeypatch.setattr("app.services.pptx_processor.subprocess.run", unexpected_conversion)
    assert render_pptx_slide_preview(source_path, 1, cache_path) == rendered


def test_pptx_preview_rejects_out_of_range_slide() -> None:
    pptx_bytes = _build_test_pptx()
    upload_resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("slides.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    document_id = upload_resp.json()["document_id"]

    response = client.get(f"/api/v1/documents/{document_id}/preview/99")

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_PAGE"


def test_upload_rejects_zip_package_without_presentation() -> None:
    invalid_pptx = io.BytesIO()
    with zipfile.ZipFile(invalid_pptx, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("not-a-presentation.pptx", invalid_pptx.getvalue(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_PPTX"


def test_upload_rejects_presentation_with_no_slides() -> None:
    empty_pptx = io.BytesIO()
    with zipfile.ZipFile(empty_pptx, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<presentation/>")

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.pptx", empty_pptx.getvalue(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_PPTX"


def test_pptx_selected_page_removal_preserves_shared_layout_watermark() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "shared-layout.pptx"
        source_path.write_bytes(_add_shared_layout(_build_test_pptx()))

        cleaned_bytes, pages_affected, skipped_ids = remove_pptx_watermarks(
            source_path,
            [_gamma_candidate()],
            pages_filter={1},
        )

    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as archive:
        layout = archive.read("ppt/slideLayouts/slideLayout1.xml").decode("utf-8")

    assert "Made with Gamma" in layout
    assert pages_affected == []
    assert skipped_ids == ["shared-layout-gamma"]


def test_pptx_all_page_removal_removes_shared_layout_watermark() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "shared-layout.pptx"
        source_path.write_bytes(_add_shared_layout(_build_test_pptx()))

        cleaned_bytes, pages_affected, skipped_ids = remove_pptx_watermarks(
            source_path,
            [_gamma_candidate()],
        )

    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as archive:
        layout = archive.read("ppt/slideLayouts/slideLayout1.xml").decode("utf-8")

    assert "Made with Gamma" not in layout
    assert pages_affected == [1, 2]
    assert skipped_ids == []


def test_pptx_scanner_candidate_removes_shared_corner_image() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "shared-layout.pptx"
        source_path.write_bytes(
            _add_shared_layout(
                _build_test_pptx(watermark_text="Scanned with CamScanner"),
                watermark_text="Scanned with CamScanner",
                include_corner_image=True,
            )
        )
        candidate = WatermarkCandidate(
            candidate_id="shared-layout-scanner",
            type="text",
            text="Scanned with CamScanner",
            page=1,
            bbox=(78.74, 472.44, 393.7, 511.81),
            rotation_degrees=0,
            confidence=0.95,
            reasons=["Recognized watermark text"],
        )

        cleaned_bytes, pages_affected, skipped_ids = remove_pptx_watermarks(
            source_path,
            [candidate],
        )

    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as archive:
        layout = archive.read("ppt/slideLayouts/slideLayout1.xml").decode("utf-8")

    assert "Scanned with CamScanner" not in layout
    assert "<p:pic>" not in layout
    assert pages_affected == [1, 2]
    assert skipped_ids == []


def test_pptx_manual_page_selection_preserves_shared_layout() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        source_path = Path(temp_dir) / "shared-layout.pptx"
        source_path.write_bytes(_add_shared_layout(_build_test_pptx()))

        cleaned_bytes, pages_affected = remove_pptx_manual_regions(
            source_path,
            [ManualRegion(page=1, x0=0.05, y0=0.8, x1=0.45, y1=0.98)],
            apply_to_all_pages=False,
        )

    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as archive:
        layout = archive.read("ppt/slideLayouts/slideLayout1.xml").decode("utf-8")

    assert "Made with Gamma" in layout
    assert pages_affected == []


def test_no_false_positives_on_normal_document_text() -> None:
    """Test that normal body text (containing words like democracy, author names, repeated headers) is NOT falsely flagged."""
    normal_texts = [
        "Fukuyama's 'End of History' thesis suggested the final triumph of liberal democracy.",
        "Meaning and Concept of Ideology",
        "Abdullah Waqar",
        "Submitted by:",
        "Naeem Ilyas",
        "Ahmad Raza",
        "Daniyal Shahid",
        "Department of Computer Science, National University of Modern Languages",
    ]

    pages = []
    for page_num in range(1, 4):
        text_objs = [
            TextObject(
                text=txt,
                page=page_num,
                bbox=(50.0, 100.0 + idx * 30.0, 450.0, 120.0 + idx * 30.0),
                font="Times-Roman",
                size=12.0,
                rotation_degrees=0.0,
            )
            for idx, txt in enumerate(normal_texts)
        ]
        pages.append(
            PageAnalysis(
                page_number=page_num,
                width=612.0,
                height=792.0,
                is_scanned=False,
                extractable_text_length=sum(len(t.text) for t in text_objs),
                text_object_count=len(text_objs),
                image_count=0,
                text_objects=text_objs,
                images=[],
            )
        )

    analysis = DocumentAnalysisResponse(
        document_id="doc-normal",
        page_count=3,
        total_text_objects=len(normal_texts) * 3,
        total_images=0,
        appears_scanned=False,
        pages=pages,
    )

    candidates = generate_candidates(analysis)
    # None of these normal body lines should be detected as watermarks
    assert len(candidates) == 0, f"False positives detected: {[c.text for c in candidates]}"


def test_pptx_manual_selection_removal() -> None:
    """Test removing watermarks from PPTX using manual region selection."""
    pptx_bytes = _build_test_pptx(watermark_text="UNAUTHORIZED COPY", title_text="Financial Q4 Review")
    upload_resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("financial.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert upload_resp.status_code == 200
    doc_id = upload_resp.json()["document_id"]

    # Manual region over watermark in normalized coords [0, 1]
    # Slide is 960 x 540 pt: wm_y0 is ~472pt (~0.875)
    removal_resp = client.post(
        f"/api/v1/documents/{doc_id}/manual-remove",
        json={
            "regions": [
                {
                    "page": 1,
                    "x0": 0.05,
                    "y0": 0.80,
                    "x1": 0.45,
                    "y1": 0.98,
                }
            ],
            "apply_to_all_pages": False,
        },
    )
    assert removal_resp.status_code == 200
    data = removal_resp.json()
    assert 1 in data["pages_affected"]

    # Download cleaned PPTX and check that title remains while watermark is gone
    dl_resp = client.get(f"/api/v1/documents/{doc_id}/download")
    assert dl_resp.status_code == 200
    cleaned_zf = zipfile.ZipFile(io.BytesIO(dl_resp.content), "r")
    slide1_xml = cleaned_zf.read("ppt/slides/slide1.xml").decode("utf-8")
    assert "UNAUTHORIZED COPY" not in slide1_xml
    assert "Financial Q4 Review" in slide1_xml


def test_pptx_gamma_watermark_detection_and_removal() -> None:
    """Test that PPTX layout watermarks (e.g. Gamma badge) are detected and removed."""
    gamma_path = Path("uploads/4373b740-85e1-4caa-b558-f49586746315.pptx")
    if not gamma_path.exists():
        return
    from app.services.pptx_processor import analyze_pptx, remove_pptx_watermarks
    from app.services.watermark_detector import generate_candidates

    analysis = analyze_pptx("test-gamma", gamma_path)
    candidates = generate_candidates(analysis)
    assert any("gamma" in c.text.lower() for c in candidates)

    gamma_candidates = [c for c in candidates if "gamma" in c.text.lower()]
    cleaned_bytes, pages, _ = remove_pptx_watermarks(gamma_path, gamma_candidates)
    assert len(pages) > 0
    with zipfile.ZipFile(io.BytesIO(cleaned_bytes), "r") as z:
        for name in z.namelist():
            if "slideLayout" in name and name.endswith(".xml"):
                content = z.read(name).decode("utf-8")
                assert "<p:pic>" not in content and "<p:pic " not in content
