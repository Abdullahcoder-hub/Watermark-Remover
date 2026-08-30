"""
Document Cleaner — FastAPI application entrypoint.

Phase 7 adds a periodic background sweep that deletes documents older
than settings.file_retention_minutes (project spec Section 12:
"Temporary files should be automatically deleted... implement a
cleanup worker/job that deletes abandoned files").
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import documents, health
from app.config import settings
from app.services.cleanup_service import cleanup_expired_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("document_cleaner")

# How often the background sweep runs. Independent of the retention
# window itself (settings.file_retention_minutes) — this just controls
# how promptly an expired document gets noticed after it expires.
CLEANUP_INTERVAL_SECONDS = 300


async def _cleanup_loop() -> None:
    while True:
        try:
            cleanup_expired_documents(settings.file_retention_minutes)
        except Exception:  # noqa: BLE001 - a failed sweep must not kill the background task
            logger.exception("cleanup_sweep_failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    logger.info("cleanup_task_started interval_seconds=%s retention_minutes=%s", CLEANUP_INTERVAL_SECONDS, settings.file_retention_minutes)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Document Cleaner API",
    description="Privacy-first watermark removal for documents you own or are authorized to modify.",
    version="0.1.0",
    lifespan=lifespan,
)

# Only the configured frontend origin is allowed — never "*" for an
# authenticated/credentialed API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(documents.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler so internal stack traces are never returned to
    the frontend. Details are logged server-side only.
    """
    logger.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": "Something went wrong while processing your request."},
        },
    )
