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

from app.config import settings
from app.utils.document_store import (
    DocumentRecord,
    analysis_store,
    detection_store,
    document_store,
    preview_cache,
    progress_store,
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
    for version in ("original", "current"):
        preview_pdf = settings.result_path / f"{record.document_id}.{version}.preview.pdf"
        _delete_file_if_exists(str(preview_pdf))
    analysis_store.delete(record.document_id)
    detection_store.delete(record.document_id)
    preview_cache.delete_document(record.document_id)
    progress_store.delete(record.document_id)
    document_store.delete(record.document_id)
    logger.info("cleanup_deleted job_id=%s", record.document_id)


def cleanup_orphaned_files(upload_dir: Path, result_dir: Path, retention_minutes: int) -> int:
    """
    Scan upload and result directories on disk for orphaned temporary files
    whose age exceeds the retention window. Returns count of deleted files.
    """
    import time

    cutoff_timestamp = time.time() - (retention_minutes * 60)
    deleted_count = 0

    for directory in (upload_dir, result_dir):
        if not directory or not directory.exists():
            continue
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue
            try:
                # Never delete hidden files or dotfiles
                if file_path.name.startswith("."):
                    continue
                stat = file_path.stat()
                if stat.st_mtime < cutoff_timestamp:
                    file_path.unlink(missing_ok=True)
                    deleted_count += 1
            except OSError as exc:
                logger.debug("cleanup_orphan_file_error path=%s: %s", file_path, exc)

    if deleted_count > 0:
        logger.info("cleanup_orphans_removed count=%s", deleted_count)
    return deleted_count


def cleanup_expired_documents(retention_minutes: int) -> int:
    """
    Delete every document whose upload is older than the retention
    window, both from in-memory stores and orphaned files on disk.
    Returns total count of removed records.
    """
    cutoff = utcnow() - timedelta(minutes=retention_minutes)
    expired = document_store.all_older_than(cutoff)
    for record in expired:
        delete_document(record)

    # Sweep orphaned disk files in upload and result folders
    cleanup_orphaned_files(settings.upload_path, settings.result_path, retention_minutes)

    if expired:
        logger.info("cleanup_sweep_removed count=%s", len(expired))
    return len(expired)
