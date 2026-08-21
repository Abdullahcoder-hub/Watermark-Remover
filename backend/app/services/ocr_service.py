"""
OCR service (Phase 6, project spec Section 8).

Adds a searchable, invisible text layer to scanned pages using
Tesseract (via pytesseract) — the page keeps looking exactly like the
original scan, but its text becomes selectable/searchable/copyable.

This is deliberately scoped to pages that actually need it: per the
spec ("OCR should be optional and should not unnecessarily modify
documents that already contain usable text... the system should
determine whether OCR is required"), only pages Phase 2's analyzer
flagged as scanned (near-zero extractable text) are touched. A page
that already has a real text layer is left untouched even if OCR is
requested for the whole document.

Implementation note: this uses pytesseract + PyMuPDF's invisible-text
insertion (render_mode=3) directly rather than shelling out to
ocrmypdf/Ghostscript/qpdf. Same underlying OCR engine (Tesseract), but
avoids a heavier external toolchain for what is, at its core, "render
page, run Tesseract, place invisible text at each word's position."
"""
import io
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pytesseract import Output

# Matches the resolution used elsewhere for page rendering; higher
# than the 150 DPI preview since OCR accuracy benefits from it.
OCR_DPI = 300
OCR_ZOOM = OCR_DPI / 72

# Tesseract confidence is 0-100 (or -1 for non-text regions); below
# this, a "word" is more likely noise than a real character run.
MIN_WORD_CONFIDENCE = 30


class OcrError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _ocr_page(page: "fitz.Page") -> int:
    """Run OCR on one page and insert an invisible text layer. Returns the word count added."""
    pixmap = page.get_pixmap(matrix=fitz.Matrix(OCR_ZOOM, OCR_ZOOM))
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    data = pytesseract.image_to_data(image, output_type=Output.DICT)

    words_added = 0
    for i in range(len(data["text"])):
        word = data["text"][i]
        if not word.strip():
            continue
        try:
            confidence = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            confidence = -1
        if confidence < MIN_WORD_CONFIDENCE:
            continue

        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        x0, y0 = x / OCR_ZOOM, y / OCR_ZOOM
        x1, y1 = (x + w) / OCR_ZOOM, (y + h) / OCR_ZOOM
        box_height = y1 - y0
        if box_height <= 0:
            continue

        fontsize = box_height * 0.8
        baseline_y = y1 - box_height * 0.15
        page.insert_text((x0, baseline_y), word, fontsize=fontsize, render_mode=3)
        words_added += 1

    return words_added


def add_ocr_text_layer(source: Path | bytes, target_pages: list[int]) -> tuple[bytes, dict[int, int]]:
    """
    Add an invisible OCR text layer to the given pages.

    `source` may be a path to a stored PDF, or raw PDF bytes (used when
    chaining after an earlier removal step).

    Returns (pdf_bytes, {page_number: words_added}).
    """
    words_by_page: dict[int, int] = {}

    try:
        with fitz.open(source) if isinstance(source, Path) else fitz.open(stream=source, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise OcrError("PASSWORD_PROTECTED", "This PDF is password-protected and cannot be processed.")

            for page_number in target_pages:
                if page_number < 1 or page_number > pdf.page_count:
                    continue
                page = pdf[page_number - 1]
                words_by_page[page_number] = _ocr_page(page)

            result_bytes = pdf.tobytes(garbage=4, deflate=True)
    except OcrError:
        raise
    except Exception as exc:  # noqa: BLE001 - any PyMuPDF/Tesseract failure means OCR couldn't complete
        raise OcrError("OCR_FAILED", "OCR could not be completed for this document.") from exc

    return result_bytes, words_by_page
