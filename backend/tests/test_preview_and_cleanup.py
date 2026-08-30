"""
Phase 7 tests: before/after preview (original vs current page render),
explicit deletion, and the automatic retention-based cleanup sweep.

Run with: pytest
"""
import io
import time
from datetime import timedelta
from pathlib import Path

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app
from app.services.cleanup_service import cleanup_expired_documents
from app.utils.document_store import document_store, utcnow

client = TestClient(app)


def _build_watermarked_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((50, 60), "Real body text.", fontsize=12)
    watermark_point = fitz.Point(60, 250)
    morph = (watermark_point, fitz.Matrix(30))
    page.insert_text(watermark_point, "CONFIDENTIAL", fontsize=30, morph=morph)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "test.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_preview_original_version_ignores_processing() -> None:
    """The 'original' version must keep showing the untouched upload even after removal."""
    document_id = _upload(_build_watermarked_pdf())

    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidate_ids = [c["candidate_id"] for c in detect_response.json()["candidates"]]
    client.post(f"/api/v1/documents/{document_id}/process", json={"candidate_ids": candidate_ids, "pages": "all"})

    original_response = client.get(f"/api/v1/documents/{document_id}/preview/1?version=original")
    current_response = client.get(f"/api/v1/documents/{document_id}/preview/1?version=current")

    assert original_response.status_code == 200
    assert current_response.status_code == 200
    # The watermark was removed from "current" but not from "original" —
    # the two renders must therefore differ.
    assert original_response.content != current_response.content


def test_preview_current_version_is_default() -> None:
    document_id = _upload(_build_watermarked_pdf())

    default_response = client.get(f"/api/v1/documents/{document_id}/preview/1")
    explicit_current_response = client.get(f"/api/v1/documents/{document_id}/preview/1?version=current")
    assert default_response.content == explicit_current_response.content


def test_preview_invalid_version_returns_error() -> None:
    document_id = _upload(_build_watermarked_pdf())

    response = client.get(f"/api/v1/documents/{document_id}/preview/1?version=nonsense")
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_VERSION"


def test_explicit_delete_removes_document_and_files() -> None:
    document_id = _upload(_build_watermarked_pdf())
    record = document_store.get(document_id)
    stored_path = Path(record.stored_path)
    assert stored_path.exists()

    response = client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"

    assert document_store.get(document_id) is None
    assert not stored_path.exists()

    # The document is now genuinely gone — any further operation on it 404s.
    status_response = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_response.status_code == 404


def test_delete_unknown_document_returns_404() -> None:
    response = client.delete("/api/v1/documents/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_cleanup_sweep_removes_only_expired_documents() -> None:
    fresh_id = _upload(_build_watermarked_pdf(), filename="fresh.pdf")
    old_id = _upload(_build_watermarked_pdf(), filename="old.pdf")

    old_record = document_store.get(old_id)
    stored_path = Path(old_record.stored_path)
    assert stored_path.exists()

    # Backdate the "old" document's upload time to simulate it having
    # sat around past the retention window, without needing to sleep.
    old_record.uploaded_at = utcnow() - timedelta(minutes=60)

    removed_count = cleanup_expired_documents(retention_minutes=30)
    assert removed_count == 1

    assert document_store.get(old_id) is None
    assert not stored_path.exists()
    assert document_store.get(fresh_id) is not None


def test_cleanup_sweep_is_a_no_op_when_nothing_expired() -> None:
    _upload(_build_watermarked_pdf())
    removed_count = cleanup_expired_documents(retention_minutes=30)
    assert removed_count == 0


def test_cleanup_sweep_clears_caches_for_removed_documents() -> None:
    """After cleanup, no stale analysis/detection/preview data should linger for a deleted document."""
    document_id = _upload(_build_watermarked_pdf())
    client.post(f"/api/v1/documents/{document_id}/analyze")
    client.post(f"/api/v1/documents/{document_id}/detect")
    client.get(f"/api/v1/documents/{document_id}/preview/1")

    record = document_store.get(document_id)
    record.uploaded_at = utcnow() - timedelta(minutes=60)
    cleanup_expired_documents(retention_minutes=30)

    # Document is gone entirely, so any endpoint touching it 404s —
    # if a stale cache entry were still influencing behavior, this
    # would misbehave instead of cleanly reporting not-found.
    response = client.post(f"/api/v1/documents/{document_id}/detect")
    assert response.status_code == 404
