"""
Document Cleaner — FastAPI application entrypoint.

Phase 1: upload + validation + health check only.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import documents, health
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("document_cleaner")

app = FastAPI(
    title="Document Cleaner API",
    description="Privacy-first watermark removal for documents you own or are authorized to modify.",
    version="0.1.0",
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
