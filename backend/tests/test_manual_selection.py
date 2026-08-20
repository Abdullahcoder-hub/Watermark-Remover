"""
Phase 5 tests: manual watermark region selection, the page-preview
endpoint, and the specific case that motivated this phase — a
vector-drawn icon (not a raster image) that automatic detection
cannot see at all.

Run with: pytest
"""
import io

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _build_camscanner_style_pdf(pages: int = 1) -> bytes:
    """
    Reproduces the reported bug: watermark text plus a small vector-
    drawn "icon" (paths, not an embedded image) near it. Automatic
    text detection can catch the text; automatic image detection
    structurally cannot see the icon, since it has no xref.
    """
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=400)
        page.insert_text((30, 30), f"Real report body text, page {i + 1}.", fontsize=12)
        page.insert_text(fitz.Point(40, 320), "Scanned with CamScanner", fontsize=14, color=(0.6, 0.6, 0.6))
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(20, 340, 45, 358))
        shape.draw_circle(fitz.Point(32, 349), 6)
        shape.finish(color=(0.6, 0.6, 0.6), fill=(0.6, 0.6, 0.6))
        shape.commit()
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "test.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_automatic_detection_misses_vector_icon() -> None:
    """Confirms the bug this phase exists to work around, so a regression here is caught."""
    document_id = _upload(_build_camscanner_style_pdf(pages=2))

    response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = response.json()["candidates"]

    assert any(c["type"] == "text" and "CamScanner" in c["text"] for c in candidates)
    assert not any(c["type"] == "image" for c in candidates)


def test_preview_returns_png_image() -> None:
    document_id = _upload(_build_camscanner_style_pdf())

    response = client.get(f"/api/v1/documents/{document_id}/preview/1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_preview_invalid_page_returns_error() -> None:
    document_id = _upload(_build_camscanner_style_pdf())

    response = client.get(f"/api/v1/documents/{document_id}/preview/99")
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_PAGE"


def test_manual_removal_clears_vector_icon_that_detection_missed() -> None:
    """The actual reported bug, fixed: manually box the icon area and it's gone."""
    document_id = _upload(_build_camscanner_style_pdf())

    # The icon occupies roughly x:20-45, y:340-358 on a 400x400 page.
    # Select a slightly generous box around it in fractional coordinates.
    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.03, "y0": 0.83, "x1": 0.15, "y1": 0.92}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pages_affected"] == [1]

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    assert download_response.status_code == 200

    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]
    # Render and confirm no dark pixels remain in the icon's region
    # (a genuine visual check, not just "no exception was raised").
    pix = page.get_pixmap(clip=fitz.Rect(20, 335, 50, 362))
    samples = pix.samples
    # An all-white region's raw samples are all 0xFF.
    assert all(b == 255 for b in samples), "icon region still contains non-white pixels"
    # Body text elsewhere on the page must be untouched.
    assert "Real report body text" in page.get_text()
    cleaned.close()


def test_manual_removal_preserves_body_text_outside_region() -> None:
    document_id = _upload(_build_camscanner_style_pdf())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.03, "y0": 0.83, "x1": 0.15, "y1": 0.92}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    text = cleaned[0].get_text()
    assert "Real report body text, page 1." in text
    cleaned.close()


def test_manual_removal_apply_to_all_pages() -> None:
    document_id = _upload(_build_camscanner_style_pdf(pages=2))

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={
            "regions": [{"page": 1, "x0": 0.03, "y0": 0.83, "x1": 0.15, "y1": 0.92}],
            "apply_to_all_pages": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["pages_affected"]) == {1, 2}


def test_manual_removal_chains_on_top_of_automatic_removal() -> None:
    """
    The exact reported workflow: auto-detect removes the text, then
    manual selection cleans up what detection missed (the icon) — and
    the automatic step's edits must not be lost in the process.
    """
    document_id = _upload(_build_camscanner_style_pdf())

    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    text_ids = [c["candidate_id"] for c in detect_response.json()["candidates"] if c["type"] == "text"]
    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": text_ids, "pages": "all"},
    )
    assert process_response.status_code == 200

    manual_response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.03, "y0": 0.83, "x1": 0.15, "y1": 0.92}]},
    )
    assert manual_response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]
    text = page.get_text()
    assert "CamScanner" not in text  # from the automatic step
    assert "Real report body text" in text  # preserved throughout
    pix = page.get_pixmap(clip=fitz.Rect(20, 335, 50, 362))
    assert all(b == 255 for b in pix.samples)  # icon gone, from the manual step
    cleaned.close()


def test_manual_removal_invalid_region_returns_error() -> None:
    document_id = _upload(_build_camscanner_style_pdf())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.5, "y0": 0.5, "x1": 0.1, "y1": 0.1}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_REGION"


def test_manual_removal_unknown_document_returns_404() -> None:
    response = client.post(
        "/api/v1/documents/does-not-exist/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}]},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"
