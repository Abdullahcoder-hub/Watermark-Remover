"""
Watermark candidate models (Phase 3).

A candidate is a scored guess at "this might be a watermark", built on
top of the raw structure Phase 2's analyzer produces. Nothing here is
removed automatically — the user selects which candidates to act on
before /process runs (see Section 3 of the project spec: "Do not
automatically remove low-confidence candidates").
"""
from typing import Literal

from pydantic import BaseModel


class WatermarkCandidate(BaseModel):
    candidate_id: str
    type: Literal["text"]  # "image" / "scanned_region" candidates arrive in later phases
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    rotation_degrees: float
    confidence: float
    reasons: list[str]


class DetectionResponse(BaseModel):
    success: bool = True
    document_id: str
    candidate_count: int
    candidates: list[WatermarkCandidate]
