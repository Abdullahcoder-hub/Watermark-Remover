"""
Phase 4 tests: image watermark candidate detection, image removal, and
mixed text+image /process requests.

Run with: pytest
"""
import io

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _logo_bytes() -> bytes:
    """A small solid-fill image used as a stand-in for a logo/stamp watermark."""
    src = fitz.open()
    src_page = src.new_page(width=100, height=100)
    src_page.draw_circle(fitz.Point(50, 50), 40, color=(0.6, 0.6, 0.9), fill=(0.6, 0.6, 0.9))
    img_bytes = src_page.get_pixmap().tobytes("png")
    src.close()
    return img_bytes


def _build_image_watermarked_pdf(pages: int = 2) -> bytes:
    """
    A multi-page PDF with body text plus the same small logo image
    repeated, roughly centered, on every page — a plausible image
    watermark per the detector's heuristics.
    """
    logo = _logo_bytes()
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=400)
        page.insert_text((30, 30), f"Report body text, page {i + 1}.", fontsize=12)
        # Centered-ish placement, moderate size (~6% of page area).
        page.insert_image(fitz.Rect(150, 150, 250, 250), stream=logo)
    data = doc.tobytes()
    doc.close()
    return data


def _build_full_page_scan_pdf() -> bytes:
    """A page that is essentially one large scanned image — should NOT be flagged as an image watermark."""
    src = fitz.open()
    src_page = src.new_page(width=100, height=100)
    src_page.draw_rect(fitz.Rect(0, 0, 100, 100), fill=(0.9, 0.9, 0.9))
    img_bytes = src_page.get_pixmap().tobytes("png")
    src.close()

    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_image(fitz.Rect(0, 0, 400, 400), stream=img_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "test.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_detect_finds_repeated_centered_image() -> None:
    document_id = _upload(_build_image_watermarked_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 200
    body = response.json()

    image_candidates = [c for c in body["candidates"] if c["type"] == "image"]
    assert len(image_candidates) == 2  # one per page
    for candidate in image_candidates:
        assert candidate["confidence"] > 0.5  # repeated + centered + moderate size
        assert candidate["xref"] is not None
        assert "roughly centered on the page" in candidate["reasons"]


def test_detect_excludes_full_page_scan_image() -> None:
    """A full-bleed scanned page image is the document's content, not a watermark overlay."""
    document_id = _upload(_build_full_page_scan_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 200
    body = response.json()

    image_candidates = [c for c in body["candidates"] if c["type"] == "image"]
    assert image_candidates == []


def test_process_removes_selected_image_and_preserves_other_page() -> None:
    document_id = _upload(_build_image_watermarked_pdf(pages=2))

    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = detect_response.json()["candidates"]
    image_ids = [c["candidate_id"] for c in candidates if c["type"] == "image"]
    assert len(image_ids) == 2

    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": image_ids, "pages": "current", "current_page": 1},
    )
    assert process_response.status_code == 200
    body = process_response.json()
    assert body["pages_affected"] == [1]
    assert body["removed_count"] == 1  # only page 1's image was in scope

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    assert download_response.status_code == 200

    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    assert cleaned[0].get_image_info() == []  # image removed from page 1
    assert len(cleaned[1].get_image_info()) == 1  # page 2's copy untouched
    assert "Report body text, page 1." in cleaned[0].get_text()  # body text preserved
    assert "Report body text, page 2." in cleaned[1].get_text()
    cleaned.close()


def test_process_mixed_text_and_image_candidates() -> None:
    """A single /process call removing both a text and an image watermark together."""
    logo = _logo_bytes()
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((30, 30), "Real body content for the report.", fontsize=12)
    watermark_point = fitz.Point(60, 300)
    morph = (watermark_point, fitz.Matrix(25))
    page.insert_text(watermark_point, "SAMPLE", fontsize=28, morph=morph)
    page.insert_image(fitz.Rect(150, 150, 250, 250), stream=logo)
    pdf_bytes = doc.tobytes()
    doc.close()

    document_id = _upload(pdf_bytes)
    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = detect_response.json()["candidates"]
    assert any(c["type"] == "text" for c in candidates)
    assert any(c["type"] == "image" for c in candidates)

    all_ids = [c["candidate_id"] for c in candidates]
    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": all_ids, "pages": "all"},
    )
    assert process_response.status_code == 200
    body = process_response.json()
    assert body["removed_count"] == len(all_ids)

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    remaining_text = cleaned[0].get_text()
    assert "SAMPLE" not in remaining_text
    assert "Real body content" in remaining_text
    assert cleaned[0].get_image_info() == []
    cleaned.close()
