"""
Pydantic models for document upload requests/responses.
"""
from datetime import datetime

from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    success: bool = True
    document_id: str
    original_filename: str
    size_bytes: int
    page_count: int | None = None
    uploaded_at: datetime
    status: str = "uploaded"


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str = "ok"
    app_env: str
