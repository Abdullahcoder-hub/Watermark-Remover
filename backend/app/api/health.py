from fastapi import APIRouter

from app.config import settings
from app.schemas.document import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", app_env=settings.app_env)
