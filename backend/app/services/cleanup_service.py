"""
Automatic cleanup (Phase 7, project spec Section 12: "Temporary files
should be automatically deleted... implement a cleanup worker/job
that deletes abandoned files").

Two paths call into this module:
  - A periodic background task (started in main.py's lifespan) that
    sweeps every document older than settings.file_retention_minutes.
  - The explicit DELETE /{id} endpoint, for a user who wants their
    document gone immediately rather than waiting for the sweep.

Both ultimately do the same thing for a given record: remove its
files from disk, drop its cached analysis/detection/preview data, and
remove it from the document store. Deletion is best-effort — a
missing file (already gone) is not an error, since the end state
("this document's data no longer exists") is what matters.
"""
import logging
from datetime import timedelta
from pathlib import Path

from app.utils.document_store import (
    DocumentRecord,
    analysis_store,
    detection_store,
    document_store,
    preview_cache,
    utcnow,
)

logger = logging.getLogger("document_cleaner")


def _delete_file_if_exists(path_str: str) -> None:
    if not path_str:
        return
    path = Path(path_str)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Best-effort: a locked or already-removed file shouldn't crash
        # the sweep. Logged for visibility, never surfaced to a user.
        logger.warning("cleanup_file_delete_failed path=%s", path_str)


def delete_document(record: DocumentRecord) -> None:
    """Remove one document's files, caches, and store entry entirely."""
    _delete_file_if_exists(record.stored_path)
    _delete_file_if_exists(record.result_path)
    analysis_store.delete(record.document_id)
    detection_store.delete(record.document_id)
    preview_cache.delete_document(record.document_id)
    document_store.delete(record.document_id)
    logger.info("cleanup_deleted job_id=%s", record.document_id)


def cleanup_expired_documents(retention_minutes: int) -> int:
    """
    Delete every document whose upload is older than the retention
    window. Returns the number of documents removed.
    """
    cutoff = utcnow() - timedelta(minutes=retention_minutes)
    expired = document_store.all_older_than(cutoff)
    for record in expired:
        delete_document(record)
    if expired:
        logger.info("cleanup_sweep_removed count=%s", len(expired))
    return len(expired)
