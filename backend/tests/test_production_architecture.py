"""
Production Architecture & Security Verification Tests:
- Multi-orientation PDFs (Portrait, Landscape, Mixed)
- Max page limit enforcement
- Security & Path traversal protection
- Concurrent job isolation
- File cleanup on error & expiration
"""
import io
import pytest
import fitz  # PyMuPDF
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.config import settings
from app.utils.document_store import document_store

client = TestClient(app)


def _create_test_pdf(pages_specs: list[tuple[float, float, str]]) -> bytes:
    """Creates a PDF with custom page dimensions, orientation, and content."""
    doc = fitz.open()
    for w, h, text in pages_specs:
        page = doc.new_page(width=w, height=h)
        page.insert_text((50, 50), text, fontsize=14)
        page.insert_text((w / 2 - 50, h / 2), "CONFIDENTIAL", fontsize=24, rotate=0)
    data = doc.tobytes()
    doc.close()
    return data


def test_portrait_landscape_mixed_orientation_pdf() -> None:
    """Tests that documents with varying page sizes and orientations are handled dynamically."""
    # Page 1: Portrait A4 (595 x 842)
    # Page 2: Landscape A4 (842 x 595)
    # Page 3: US Letter Portrait (612 x 792)
    # Page 4: US Letter Landscape (792 x 612)
    pdf_bytes = _create_test_pdf([
        (595, 842, "Page 1 - Portrait A4"),
        (842, 595, "Page 2 - Landscape A4"),
        (612, 792, "Page 3 - Letter Portrait"),
        (792, 612, "Page 4 - Letter Landscape"),
    ])

    files = {"file": ("multi_orientation.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    upload_res = client.post("/api/v1/documents/upload", files=files)
    assert upload_res.status_code == 200
    doc_id = upload_res.json()["document_id"]
    assert upload_res.json()["page_count"] == 4

    # Analyze
    analyze_res = client.post(f"/api/v1/documents/{doc_id}/analyze")
    assert analyze_res.status_code == 200
    pages = analyze_res.json()["pages"]
    assert len(pages) == 4
    assert pages[0]["width"] == 595.0 and pages[0]["height"] == 842.0
    assert pages[1]["width"] == 842.0 and pages[1]["height"] == 595.0

    # Detect
    detect_res = client.post(f"/api/v1/documents/{doc_id}/detect")
    assert detect_res.status_code == 200
    candidates = detect_res.json()["candidates"]
    assert len(candidates) >= 4

    # Process all
    cand_ids = [c["candidate_id"] for c in candidates]
    process_res = client.post(f"/api/v1/documents/{doc_id}/process", json={"candidate_ids": cand_ids, "pages": "all"})
    assert process_res.status_code == 200
    assert process_res.json()["removed_count"] >= 4

    # Download
    download_res = client.get(f"/api/v1/documents/{doc_id}/download")
    assert download_res.status_code == 200
    cleaned_doc = fitz.open(stream=download_res.content, filetype="pdf")
    assert cleaned_doc.page_count == 4
    assert "CONFIDENTIAL" not in cleaned_doc[0].get_text()
    assert "CONFIDENTIAL" not in cleaned_doc[1].get_text()
    cleaned_doc.close()


def test_max_pages_limit_exceeded() -> None:
    """Tests that uploading a PDF exceeding settings.max_pages is rejected."""
    orig_max = settings.max_pages
    try:
        settings.max_pages = 3
        pdf_bytes = _create_test_pdf([
            (300, 300, "Page 1"),
            (300, 300, "Page 2"),
            (300, 300, "Page 3"),
            (300, 300, "Page 4"),
        ])
        files = {"file": ("four_pages.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        res = client.post("/api/v1/documents/upload", files=files)
        assert res.status_code == 400
        assert res.json()["detail"]["error"]["code"] == "PAGE_LIMIT_EXCEEDED"
    finally:
        settings.max_pages = orig_max


def test_path_traversal_protection_on_download() -> None:
    """Tests that arbitrary file access via manipulated paths or document IDs is prevented."""
    res = client.get("/api/v1/documents/../../etc/passwd/download")
    assert res.status_code in (404, 400)

    res2 = client.get("/api/v1/documents/invalid-uuid-1234/download")
    assert res2.status_code == 404


def test_concurrent_job_isolation() -> None:
    """Tests that two separate uploaded documents operate in complete isolation."""
    pdf_a = _create_test_pdf([(400, 400, "User A Private Content")])
    pdf_b = _create_test_pdf([(500, 500, "User B Secret Report")])

    files_a = {"file": ("user_a.pdf", io.BytesIO(pdf_a), "application/pdf")}
    files_b = {"file": ("user_b.pdf", io.BytesIO(pdf_b), "application/pdf")}

    res_a = client.post("/api/v1/documents/upload", files=files_a)
    res_b = client.post("/api/v1/documents/upload", files=files_b)

    id_a = res_a.json()["document_id"]
    id_b = res_b.json()["document_id"]

    assert id_a != id_b

    # Process A
    client.post(f"/api/v1/documents/{id_a}/analyze")
    det_a = client.post(f"/api/v1/documents/{id_a}/detect").json()
    client.post(f"/api/v1/documents/{id_a}/process", json={"candidate_ids": [c["candidate_id"] for c in det_a["candidates"]], "pages": "all"})

    # Check status of B remains separate
    stat_b = client.get(f"/api/v1/documents/{id_b}/status").json()
    assert stat_b["status"] == "uploaded"

    # Download A does not leak B's content
    down_a = client.get(f"/api/v1/documents/{id_a}/download")
    doc_a = fitz.open(stream=down_a.content, filetype="pdf")
    text_a = doc_a[0].get_text()
    assert "User A Private Content" in text_a
    assert "User B Secret Report" not in text_a
    doc_a.close()
