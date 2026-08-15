"""
Phase 1 tests: upload validation and the /upload endpoint.

Run with: pytest
"""
import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF"
)


def test_health_check() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_valid_pdf() -> None:
    files = {"file": ("sample.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["original_filename"] == "sample.pdf"
    assert body["page_count"] == 1


def test_upload_rejects_non_pdf_extension() -> None:
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_EXTENSION"


def test_upload_rejects_fake_pdf_extension_with_wrong_magic_bytes() -> None:
    files = {"file": ("fake.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_PDF"


def test_upload_rejects_empty_file() -> None:
    files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "EMPTY_FILE"


def test_upload_rejects_oversized_file(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "max_upload_size_mb", 0)
    files = {"file": ("sample.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "FILE_TOO_LARGE"
