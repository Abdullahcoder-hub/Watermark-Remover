"""
Manual selection models (Phase 5, project spec Section 5).

Automatic detection won't catch everything — notably, vector-drawn
graphics (e.g. a logo/icon drawn with paths rather than an embedded
raster image) are invisible to both the text and image detectors.
Manual selection is the deliberately blunt fallback: the user marks an
exact region on a page, and everything within it — text, images, and
vector graphics alike — is removed, no confidence scoring involved.
"""
from pydantic import BaseModel, Field


class ManualRegion(BaseModel):
    page: int
    # Fractional coordinates in [0, 1], relative to that page's own
    # width/height, top-left origin — resolution-independent so the
    # frontend doesn't need to know the PDF's point dimensions.
    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)


class ManualRemovalRequest(BaseModel):
    regions: list[ManualRegion] = Field(min_length=1)
    # If true, each region's fractional box is replicated onto every
    # page of the document (proportionally, via that page's own
    # dimensions) instead of only the page it was drawn on.
    apply_to_all_pages: bool = False


class ManualRemovalResponse(BaseModel):
    success: bool = True
    document_id: str
    status: str = "processed"
    regions_applied: int
    pages_affected: list[int]
