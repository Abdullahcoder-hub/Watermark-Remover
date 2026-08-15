"""
Response models for the document analyzer (Phase 2).

These describe raw extracted structure (text objects, images, whether
a page is scanned) — not watermark candidates. Watermark scoring is a
later phase; this is the data it will be built on top of.
"""
from pydantic import BaseModel


class TextObject(BaseModel):
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    rotation_degrees: float
    color: str | None = None


class ImageObject(BaseModel):
    page: int
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    has_alpha: bool
    coverage_ratio: float  # fraction of the page area this image covers


class PageAnalysis(BaseModel):
    page_number: int
    width: float
    height: float
    is_scanned: bool
    extractable_text_length: int
    text_object_count: int
    image_count: int
    text_objects: list[TextObject]
    images: list[ImageObject]


class DocumentAnalysisResponse(BaseModel):
    success: bool = True
    document_id: str
    page_count: int
    total_text_objects: int
    total_images: int
    appears_scanned: bool
    pages: list[PageAnalysis]
