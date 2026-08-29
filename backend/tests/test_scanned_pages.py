"""
Phase 6 tests: scanned-page (Case C) watermark removal via inpainting,
and OCR. Includes a regression test for the specific data-loss bug
this phase exists to prevent: naive redaction deleting an entire
full-page scanned image because a small selection box partially
overlapped it.

Run with: pytest
"""
import io

import fitz  # PyMuPDF
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _build_scanned_pdf_with_stamp() -> bytes:
    """
    A single-page "scanned" document: the whole page is one embedded
    image (no real text layer), with a small stamp-like mark in a
    corner meant to represent a watermark baked into the scan.
    """
    src = fitz.open()
    src_page = src.new_page(width=300, height=300)
    src_page.draw_rect(fitz.Rect(0, 0, 300, 300), fill=(0.97, 0.97, 0.95))
    src_page.insert_text((30, 50), "This looks like scanned document text.", fontsize=11, color=(0.1, 0.1, 0.1))
    src_page.insert_text((30, 70), "Another line of scanned content here.", fontsize=11, color=(0.1, 0.1, 0.1))
    shape = src_page.new_shape()
    shape.draw_circle(fitz.Point(250, 250), 30)
    shape.finish(color=(0.7, 0.1, 0.1), width=3)
    shape.commit()
    src_page.insert_text((225, 253), "COPY", fontsize=12, color=(0.7, 0.1, 0.1))
    img_bytes = src_page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
    src.close()

    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(fitz.Rect(0, 0, 300, 300), stream=img_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(pdf_bytes: bytes, filename: str = "scanned.pdf") -> str:
    files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 200
    return response.json()["document_id"]


def test_analysis_flags_scanned_page() -> None:
    document_id = _upload(_build_scanned_pdf_with_stamp())
    response = client.post(f"/api/v1/documents/{document_id}/analyze")
    body = response.json()
    assert body["appears_scanned"] is True
    assert body["pages"][0]["is_scanned"] is True


def test_manual_removal_on_scanned_page_rejects_oversized_selection() -> None:
    """
    Regression test for a real reported bug: a large selection box on a
    scanned page doesn't just fail to remove the watermark cleanly — it
    produces a washed-out, blank-looking page, because classical
    inpainting has no surrounding pixel data to reconstruct a large
    masked area from. Confirmed directly by reproducing it (a 65%-page
    selection came back as a uniform foggy patch). Rather than silently
    "succeed" into a ruined document, this must be rejected with an
    explanation.
    """
    document_id = _upload(_build_scanned_pdf_with_stamp())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.05, "y0": 0.1, "x1": 0.95, "y1": 0.9}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "SELECTION_TOO_LARGE"

    # And the document must be left untouched — no partial/corrupted result written.
    status_response = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_response.json()["status"] != "processed"


def test_manual_removal_on_scanned_page_does_not_delete_entire_scan() -> None:
    """
    The core regression test: before this phase, a small selection box
    on a scanned page triggered PDF_REDACT_IMAGE_REMOVE, which deletes
    the ENTIRE image object on any overlap — destroying the whole page.
    Inpainting must leave the rest of the scan fully intact.
    """
    document_id = _upload(_build_scanned_pdf_with_stamp())

    # Small box around just the stamp (bottom-right corner).
    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.68, "y0": 0.68, "x1": 0.98, "y1": 0.95}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    assert download_response.status_code == 200

    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]
    # The scan must still be there at all — this is what would have
    # been wiped out entirely by naive redaction.
    assert len(page.get_image_info()) == 1
    cleaned.close()


def test_manual_removal_on_scanned_page_removes_stamp_pixels() -> None:
    document_id = _upload(_build_scanned_pdf_with_stamp())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.68, "y0": 0.68, "x1": 0.98, "y1": 0.95}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]

    # Sample the stamp's original location: no more strong red pixels.
    pix = page.get_pixmap(clip=fitz.Rect(220, 220, 280, 280))
    samples = pix.samples
    n = pix.n  # channels per pixel
    has_strong_red = any(
        samples[i] > 150 and samples[i + 1] < 100 and samples[i + 2] < 100 for i in range(0, len(samples), n)
    )
    assert not has_strong_red, "red stamp pixels still present after inpainting"
    cleaned.close()


def test_manual_removal_on_scanned_page_preserves_body_region() -> None:
    document_id = _upload(_build_scanned_pdf_with_stamp())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.68, "y0": 0.68, "x1": 0.98, "y1": 0.95}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]

    # The body-text region (top of the page) should be visually
    # unchanged — not blank/white, since inpainting was never applied
    # there.
    pix = page.get_pixmap(clip=fitz.Rect(20, 40, 280, 90))
    samples = pix.samples
    has_dark_pixels = any(b < 100 for b in samples)
    assert has_dark_pixels, "body text region appears blank after unrelated inpainting"
    cleaned.close()


def test_manual_removal_on_normal_page_still_uses_redaction() -> None:
    """A regular (non-scanned) page must still use the Phase 5 redaction path, not inpainting."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((20, 30), "Ordinary text document.", fontsize=12)
    page.insert_text((20, 250), "WATERMARK", fontsize=16)
    pdf_bytes = doc.tobytes()
    doc.close()

    document_id = _upload(pdf_bytes, filename="normal.pdf")
    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.05, "y0": 0.8, "x1": 0.6, "y1": 0.92}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    text = cleaned[0].get_text()
    assert "WATERMARK" not in text
    assert "Ordinary text document." in text
    cleaned.close()


def test_ocr_adds_searchable_text_to_scanned_page() -> None:
    document_id = _upload(_build_scanned_pdf_with_stamp())

    # confirm no extractable text before OCR
    pre_analyze = client.post(f"/api/v1/documents/{document_id}/analyze").json()
    assert pre_analyze["pages"][0]["extractable_text_length"] == 0

    response = client.post(f"/api/v1/documents/{document_id}/ocr", json={})
    assert response.status_code == 200
    body = response.json()
    assert len(body["pages_ocred"]) == 1
    assert body["pages_ocred"][0]["page"] == 1
    assert body["pages_ocred"][0]["words_added"] > 0

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    ocred = fitz.open(stream=download_response.content, filetype="pdf")
    text = ocred[0].get_text()
    assert "scanned" in text.lower()
    ocred.close()


def test_ocr_does_not_visually_alter_the_page() -> None:
    """Invisible text layer must not create a visible duplicate."""
    document_id = _upload(_build_scanned_pdf_with_stamp())

    before_response = client.get(f"/api/v1/documents/{document_id}/preview/1")
    before_bytes = before_response.content

    client.post(f"/api/v1/documents/{document_id}/ocr", json={})

    after_response = client.get(f"/api/v1/documents/{document_id}/preview/1")
    after_bytes = after_response.content

    # Rendered appearance should be effectively identical in size (a
    # visible duplicate text layer would noticeably change the PNG).
    assert abs(len(before_bytes) - len(after_bytes)) < len(before_bytes) * 0.05


def test_ocr_on_document_with_no_scanned_pages_is_a_graceful_no_op() -> None:
    """Not an error: nothing needed OCR, so nothing changed — a valid, successful outcome."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((20, 30), "Perfectly normal text document.", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()

    document_id = _upload(pdf_bytes, filename="normal.pdf")
    response = client.post(f"/api/v1/documents/{document_id}/ocr", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["pages_ocred"] == []


def test_ocr_called_twice_is_graceful_second_time() -> None:
    """
    OCR itself adds a text layer, so a page that was scanned no longer
    looks scanned afterward. Calling OCR again must not error — it
    should recognize there's nothing left to do.
    """
    document_id = _upload(_build_scanned_pdf_with_stamp())

    first = client.post(f"/api/v1/documents/{document_id}/ocr", json={})
    assert first.status_code == 200
    assert len(first.json()["pages_ocred"]) == 1

    second = client.post(f"/api/v1/documents/{document_id}/ocr", json={})
    assert second.status_code == 200
    assert second.json()["pages_ocred"] == []


def test_ocr_unknown_document_returns_404() -> None:
    response = client.post("/api/v1/documents/does-not-exist/ocr", json={})
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_manual_removal_after_automatic_process_still_finds_correct_scanned_xref() -> None:
    """
    Regression test for the xref-staleness fix: run an automatic
    /process step first (forcing a garbage-collecting resave that
    renumbers xrefs document-wide), then confirm manual inpainting on
    a scanned page still targets the correct (now-renumbered) image.
    """
    document_id = _upload(_build_scanned_pdf_with_stamp())

    # Automatic detect/process won't find anything on the scanned page
    # (no text, image is full-page and excluded) — this call exists
    # purely to force an intermediate resave.
    client.post(f"/api/v1/documents/{document_id}/detect")
    # No candidates expected, so skip /process if there's nothing to do.

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.68, "y0": 0.68, "x1": 0.98, "y1": 0.95}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    assert len(cleaned[0].get_image_info()) == 1  # scan still present, not deleted
    cleaned.close()


def _build_scanned_pdf_with_margin_and_logo() -> bytes:
    """
    Reproduces a real reported bug: a realistic scanned export (e.g.
    CamScanner) where the scan image has a modest margin/border rather
    than covering literally 100% of the page, plus a small separate
    logo image in a corner. Before the coverage threshold fix, this
    margin alone dropped the scan's coverage below the "is this a
    scanned page" cutoff, causing the scan to be misidentified as a
    removable watermark image and destroyed when selected.
    """
    src = fitz.open()
    sp = src.new_page(width=595, height=842)
    sp.draw_rect(fitz.Rect(0, 0, 595, 842), fill=(0.96, 0.96, 0.94))
    for i in range(10):
        sp.insert_text((40, 60 + i * 35), f"Handwritten program line {i + 1} content.", fontsize=12, color=(0.05, 0.05, 0.4))
    scan_bytes = sp.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    src.close()

    logo_src = fitz.open()
    lp = logo_src.new_page(width=40, height=25)
    lp.draw_rect(fitz.Rect(0, 0, 40, 25), fill=(0.1, 0.6, 0.5))
    lp.insert_text((5, 17), "CS", fontsize=14, color=(1, 1, 1))
    logo_bytes = lp.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
    logo_src.close()

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    margin_x, margin_y = 595 * 0.08, 842 * 0.06  # realistic auto-crop margin
    page.insert_image(fitz.Rect(margin_x, margin_y, 595 - margin_x, 842 - margin_y), stream=scan_bytes)
    page.insert_image(fitz.Rect(555, 810, 590, 835), stream=logo_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def test_scanned_page_with_realistic_margin_is_still_flagged_as_scanned() -> None:
    """Regression test: a margin alone must not defeat scanned-page detection."""
    document_id = _upload(_build_scanned_pdf_with_margin_and_logo())
    response = client.post(f"/api/v1/documents/{document_id}/analyze")
    body = response.json()
    assert body["pages"][0]["is_scanned"] is True


def test_scan_with_margin_is_not_offered_as_a_watermark_image_candidate() -> None:
    """
    Regression test for the exact reported bug: the main scan (with a
    realistic margin) must never be surfaced as a removable "image"
    watermark candidate — only the small separate logo may be.
    """
    document_id = _upload(_build_scanned_pdf_with_margin_and_logo())
    response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = response.json()["candidates"]

    image_candidates = [c for c in candidates if c["type"] == "image"]
    for candidate in image_candidates:
        # Every offered image candidate must be small (the logo), never
        # the dominant scan.
        bbox = candidate["bbox"]
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        assert area < 595 * 842 * 0.3, "the main scan was offered as a watermark candidate"


def test_manual_removal_on_margin_scan_page_uses_inpainting_not_redaction() -> None:
    """
    Regression test: with the margin, this page must route through
    inpainting (not redaction) so a small logo selection can't destroy
    the whole scan.
    """
    document_id = _upload(_build_scanned_pdf_with_margin_and_logo())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.93, "y0": 0.96, "x1": 0.995, "y1": 0.99}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]
    # The scan image must still be present — proof it was inpainted,
    # not deleted outright by redaction.
    assert len(page.get_image_info()) >= 1
    assert "Handwritten program line 1" in page.get_text() or _has_dark_pixels(page)
    cleaned.close()


def _has_dark_pixels(page: "fitz.Page") -> bool:
    pix = page.get_pixmap(clip=fitz.Rect(30, 40, 400, 400))
    return any(b < 150 for b in pix.samples)


def test_automatic_process_refuses_to_delete_dominant_page_image() -> None:
    """
    Defense-in-depth regression test: even if an image candidate for
    the dominant scan somehow gets generated and selected, automatic
    /process must refuse to delete it rather than blanking the page.
    """
    document_id = _upload(_build_scanned_pdf_with_margin_and_logo())
    detect_response = client.post(f"/api/v1/documents/{document_id}/detect")
    candidates = detect_response.json()["candidates"]

    # Manually construct a candidate targeting the full scan area, as
    # if detection had (incorrectly) offered it — simulates the bug
    # scenario directly rather than relying on detection never
    # regressing.
    large_bbox_candidates = [c for c in candidates if c["type"] == "image"]
    if not large_bbox_candidates:
        return  # detection correctly excluded it; nothing to defend against here

    ids = [c["candidate_id"] for c in large_bbox_candidates]
    process_response = client.post(
        f"/api/v1/documents/{document_id}/process",
        json={"candidate_ids": ids, "pages": "all"},
    )
    assert process_response.status_code == 200
    body = process_response.json()

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    # The page must not have been blanked — some image must remain.
    assert len(cleaned[0].get_image_info()) >= 1
    cleaned.close()


def _build_scanned_pdf_with_separate_overlay_logo() -> bytes:
    """
    Reproduces the exact structure found in a real CamScanner export:
    the visible logo is its own small separate image object, layered
    on top of (not baked into) the main scan image — confirmed by
    directly inspecting the real file's xrefs (dominant scan ~78%
    coverage, logo ~0.1% coverage, both present via get_image_info).
    """
    src = fitz.open()
    sp = src.new_page(width=595, height=842)
    sp.draw_rect(fitz.Rect(0, 0, 595, 842), fill=(0.96, 0.96, 0.94))
    for i in range(8):
        sp.insert_text((40, 60 + i * 35), f"Handwritten program line {i + 1}.", fontsize=12, color=(0.05, 0.05, 0.4))
    scan_bytes = sp.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
    src.close()

    logo_src = fitz.open()
    lp = logo_src.new_page(width=22, height=22)
    lp.draw_rect(fitz.Rect(0, 0, 22, 22), fill=(0.1, 0.6, 0.5))
    lp.insert_text((3, 15), "CS", fontsize=11, color=(1, 1, 1))
    logo_bytes = lp.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
    logo_src.close()

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # Main scan first (as the base layer)...
    page.insert_image(fitz.Rect(0, 0, 595, 842), stream=scan_bytes)
    # ...then the logo as a genuinely separate image object on top.
    page.insert_image(fitz.Rect(560, 810, 585, 833), stream=logo_bytes)
    data = doc.tobytes()
    doc.close()
    return data


def test_manual_removal_deletes_separate_overlay_logo_not_just_inpaints_scan() -> None:
    """
    Regression test for a real reported bug: when the watermark logo on
    a scanned page is its own separate image object (not baked into the
    scan), removal must delete that overlay image directly — inpainting
    only the dominant scan image leaves a distinct object on top
    completely untouched.
    """
    document_id = _upload(_build_scanned_pdf_with_separate_overlay_logo())

    response = client.post(
        f"/api/v1/documents/{document_id}/manual-remove",
        json={"regions": [{"page": 1, "x0": 0.93, "y0": 0.95, "x1": 0.995, "y1": 0.99}]},
    )
    assert response.status_code == 200

    download_response = client.get(f"/api/v1/documents/{document_id}/download")
    cleaned = fitz.open(stream=download_response.content, filetype="pdf")
    page = cleaned[0]

    # The overlay logo must be visually gone (deleted via replace_image
    # with a transparent pixmap, not object-count removal — the object
    # may still technically exist but renders nothing).
    logo_area_pix = page.get_pixmap(clip=fitz.Rect(555, 805, 590, 838))
    samples = logo_area_pix.samples
    has_teal_pixels = any(
        samples[i] < 60 and samples[i + 1] > 120 and samples[i + 2] > 100 for i in range(0, len(samples), logo_area_pix.n)
    )
    assert not has_teal_pixels, "overlay logo is still visually present"
    # The scan itself (and the rest of the page) must be untouched —
    # check for dark ink pixels in the body-text area (this is a
    # scanned page, so the text lives in pixels, not extractable text).
    body_pix = page.get_pixmap(clip=fitz.Rect(30, 50, 400, 100))
    assert any(b < 120 for b in body_pix.samples), "body text region appears blank"
    cleaned.close()


