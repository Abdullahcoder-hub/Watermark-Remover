"""
Phase 3 tests: watermark candidate detection, text watermark removal,
and the /detect, /process, /download endpoints.

Run with: pytest
"""
import io

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _build_watermarked_pdf(pages: int = 2) -> bytes:
    """
    A multi-page PDF with normal body text plus a repeated, rotated
    "CONFIDENTIAL" watermark placed clear of the body text so removal
    can be verified without the known AABB-overlap caveat interfering.
    """
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=400)
        page.insert_text((50, 60), f"This is page {i + 1} body text.", fontsize=12)
        page.insert_text((50, 90), "Second line of real content.", fontsize=12)
        watermark_point = fitz.Point(60, 250)
        morph = (watermark_point, fitz.Matrix(30))
        page.insert_text(watermark_point, "CONFIDENTIAL", fontsize=30, morph=morph)
    data = doc.tobytes()
    doc.close()
    return data


def _build_plain_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 100), "Just a normal document with plain content.", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "test.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_detect_finds_repeated_rotated_watermark() -> None:
    document_id = _upload(_build_watermarked_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 200
    body = response.json()

    assert body["candidate_count"] >= 2  # one per page
    watermark_candidates = [c for c in body["candidates"] if c["text"] == "CONFIDENTIAL"]
    assert len(watermark_candidates) == 2
    for candidate in watermark_candidates:
        assert candidate["confidence"] > 0.5  # repeated + rotated + keyword match
        assert "matches common watermark wording" in candidate["reasons"]


def test_detect_without_prior_analyze_still_works() -> None:
    """/detect should run analysis automatically if it wasn't called first."""
    document_id = _upload(_build_watermarked_pdf(pages=1))

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 200
    assert response.json()["candidate_count"] >= 1


def test_detect_on_plain_document_finds_nothing() -> None:
    document_id = _upload(_build_plain_pdf())

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 200
    assert response.json()["candidate_count"] == 0


def test_process_removes_selected_watermark_and_preserves_body_text() -> None:
    document_id = _upload(_build_watermarked_pdf(pages=2))

    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = detect_response.json()["candidates"]
    watermark_ids = [c["candidate_id"] for c in candidates if c["text"] == "CONFIDENTIAL"]
    assert len(watermark_ids) == 2

    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": watermark_ids, "pages": "all"},
    )
    assert process_response.status_code == 200
    body = process_response.json()
    assert body["removed_count"] == 2
    assert body["skipped_candidate_ids"] == []
    assert set(body["pages_affected"]) == {1, 2}

    # Download and verify with a fresh PyMuPDF read: watermark gone, body text intact.
    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"

    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    for page in cleaned:
        text = page.get_text()
        assert "CONFIDENTIAL" not in text
        assert "body text" in text or "Second line" in text
    cleaned.close()


def test_process_scoped_to_current_page_only_affects_that_page() -> None:
    document_id = _upload(_build_watermarked_pdf(pages=2))

    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = detect_response.json()["candidates"]
    watermark_ids = [c["candidate_id"] for c in candidates if c["text"] == "CONFIDENTIAL"]

    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": watermark_ids, "pages": "current", "current_page": 1},
    )
    assert process_response.status_code == 200
    body = process_response.json()
    assert body["pages_affected"] == [1]
    assert body["removed_count"] == 1  # only page 1's watermark was in scope

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    assert "CONFIDENTIAL" not in cleaned[0].get_text()
    assert "CONFIDENTIAL" in cleaned[1].get_text()  # page 2 untouched
    cleaned.close()


def test_process_without_detection_returns_error() -> None:
    document_id = _upload(_build_plain_pdf())

    response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": ["nonexistent"], "pages": "all"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "NO_CANDIDATES_DETECTED"


def test_process_with_invalid_candidate_ids_returns_error() -> None:
    document_id = _upload(_build_watermarked_pdf(pages=1))
    client.post(f"/api/v1/documents/{document_id}/detect")

    response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": ["not-a-real-id"], "pages": "all"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_CANDIDATE_IDS"


def test_download_before_processing_returns_error() -> None:
    document_id = _upload(_build_plain_pdf())

    response = client.get(f"/api/v1/documents/{document_id}/download")
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "NOT_PROCESSED"


def test_detect_unknown_document_returns_404() -> None:
    response = client.post("/api/v1/documents/does-not-exist/detect")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"
