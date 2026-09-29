"""
Response models for the document analyzer (Phase 2 & Upgraded Intelligent Pipeline).

Describes extracted structure (text objects, images, scanned status, failure resilience)
across small and large documents.
"""
from pydantic import BaseModel, Field


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
    xref: int  # PDF cross-reference number; identical images reused across pages share this
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
    text_objects: list[TextObject] = Field(default_factory=list)
    images: list[ImageObject] = Field(default_factory=list)
    has_error: bool = False
    error_message: str | None = None


class DocumentAnalysisResponse(BaseModel):
    success: bool = True
    document_id: str
    page_count: int
    total_text_objects: int
    total_images: int
    appears_scanned: bool
    pages: list[PageAnalysis]
    total_scanned: int = 0
    failed_pages: list[int] = Field(default_factory=list)
