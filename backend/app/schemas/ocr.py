"""
Request/response models for the /ocr endpoint (Phase 6).
"""
from pydantic import BaseModel


class OcrRequest(BaseModel):
    # Explicit page list, or omit/empty to default to every page the
    # analyzer identified as scanned (the spec's "system should
    # determine whether OCR is required").
    pages: list[int] | None = None


class OcrPageResult(BaseModel):
    page: int
    words_added: int


class OcrResponse(BaseModel):
    success: bool = True
    document_id: str
    status: str = "processed"
    pages_ocred: list[OcrPageResult]
    # True when this call didn't run Tesseract at all because OCR was
    # already applied to this document and no explicit page list was
    # given — distinguishes "nothing to do, already searchable" from
    # "ran OCR and genuinely found nothing" for the frontend to show a
    # clear message instead of a generic error.
    already_applied: bool = False
