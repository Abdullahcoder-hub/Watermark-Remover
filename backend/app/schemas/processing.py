"""
Request/response models for the /process (watermark removal) endpoint.
"""
from typing import Literal

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    pages: Literal["current", "selected", "all"] = "all"
    current_page: int | None = None
    selected_pages: list[int] | None = None


class ProcessResponse(BaseModel):
    success: bool = True
    document_id: str
    status: str = "processed"
    requested_count: int
    removed_count: int
    skipped_candidate_ids: list[str]
    pages_affected: list[int]
