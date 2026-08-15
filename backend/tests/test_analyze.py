"""
Phase 2 tests: PDF analysis (text extraction, image detection,
scanned-page detection) and the /analyze, /status endpoints.

Run with: pytest
"""
import io

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _build_text_pdf() -> bytes:
    """A simple single-page PDF with plain extractable text, no images."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 100), "Hello, this is a real document.", fontsize=14)
    page.insert_text((50, 130), "It has multiple lines of text.", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data


def _build_watermarked_text_pdf() -> bytes:
    """A page with body text plus a large rotated 'CONFIDENTIAL' watermark span."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 100), "Body paragraph content here.", fontsize=12)
    watermark_point = fitz.Point(100, 250)
    morph = (watermark_point, fitz.Matrix(45))
    page.insert_text(watermark_point, "CONFIDENTIAL", fontsize=40, morph=morph)
    data = doc.tobytes()
    doc.close()
    return data


def _build_scanned_pdf() -> bytes:
    """A page that is essentially one full-page image with no extractable text."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    # Render a tiny source image and place it covering the whole page.
    src = fitz.open()
    src_page = src.new_page(width=100, height=100)
    src_page.draw_rect(fitz.Rect(0, 0, 100, 100), fill=(0.8, 0.8, 0.8))
    pix = src_page.get_pixmap()
    img_bytes = pix.tobytes("png")
    src.close()

    page.insert_image(fitz.Rect(0, 0, 400, 400), stream=img_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "test.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_analyze_text_document_detects_text_no_images() -> None:
    document_id = _upload(_build_text_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert response.status_code == 200
    body = response.json()

    assert body["success"] is True
    assert body["page_count"] == 1
    assert body["total_text_objects"] >= 2
    assert body["total_images"] == 0
    assert body["appears_scanned"] is False
    assert body["pages"][0]["text_object_count"] >= 2


def test_analyze_detects_rotated_watermark_span() -> None:
    document_id = _upload(_build_watermarked_text_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert response.status_code == 200
    body = response.json()

    texts = [t["text"] for t in body["pages"][0]["text_objects"]]
    assert "CONFIDENTIAL" in texts

    watermark_span = next(t for t in body["pages"][0]["text_objects"] if t["text"] == "CONFIDENTIAL")
    # Rotated 45 degrees, so rotation should not be ~0.
    assert watermark_span["rotation_degrees"] != 0.0


def test_analyze_detects_scanned_page() -> None:
    document_id = _upload(_build_scanned_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/analyze")
    assert response.status_code == 200
    body = response.json()

    assert body["appears_scanned"] is True
    assert body["pages"][0]["is_scanned"] is True
    assert body["total_images"] == 1


def test_analyze_unknown_document_returns_404() -> None:
    response = client.post("/api/v1/documents/does-not-exist/analyze")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_status_reflects_analysis_lifecycle() -> None:
    document_id = _upload(_build_text_pdf())

    status_before = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_before.json()["status"] == "uploaded"

    client.post(f"/api/v1/documents/{document_id}/analyze")

    status_after = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_after.json()["status"] == "analyzed"


def test_status_unknown_document_returns_404() -> None:
    response = client.get("/api/v1/documents/does-not-exist/status")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"
