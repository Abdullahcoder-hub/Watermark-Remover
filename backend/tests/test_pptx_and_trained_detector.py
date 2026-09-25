"""
Tests for PowerPoint (.pptx) watermark detection and removal, and the expanded
tokenless heuristic watermark knowledge base (CamScanner, Gamma, Canva, etc.).
"""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.analysis import DocumentAnalysisResponse, PageAnalysis, TextObject
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
