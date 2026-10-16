from fastapi import APIRouter

from app.config import settings
from app.schemas.document import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/v1/health", response_model=HealthResponse)
@router.get("/", response_model=HealthResponse, include_in_schema=False)
@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app_env=settings.app_env)
