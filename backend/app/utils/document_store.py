"""
In-memory document registry, analysis caching, and job progress tracking.
Thread-safe process-local state management.
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DocumentRecord:
    document_id: str
    original_filename: str
    size_bytes: int
    page_count: int | None
    uploaded_at: datetime
    status: str = "uploaded"
    stored_path: str = ""
    result_path: str = ""
    ocr_applied: bool = False


class DocumentStore:
    def __init__(self) -> None:
        self._records: dict[str, DocumentRecord] = {}
        self._lock = threading.Lock()

    def add(self, record: DocumentRecord) -> None:
        with self._lock:
            self._records[record.document_id] = record

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            return self._records.get(document_id)

    def set_status(self, document_id: str, status: str) -> None:
        with self._lock:
            record = self._records.get(document_id)
            if record is not None:
                record.status = status

    def set_result_path(self, document_id: str, result_path: str) -> None:
        with self._lock:
            record = self._records.get(document_id)
            if record is not None:
                record.result_path = result_path

    def set_ocr_applied(self, document_id: str, applied: bool) -> None:
        with self._lock:
            record = self._records.get(document_id)
            if record is not None:
                record.ocr_applied = applied

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._records.pop(document_id, None)

    def all_older_than(self, cutoff: datetime) -> list[DocumentRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.uploaded_at < cutoff]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


document_store = DocumentStore()


class AnalysisStore:
    """
    Caches the last analysis result per document so the frontend can
    re-fetch it without re-running parsing.
    """

    def __init__(self) -> None:
        self._results: dict[str, object] = {}
        self._lock = threading.Lock()

    def set(self, document_id: str, result: object) -> None:
        with self._lock:
            self._results[document_id] = result

    def get(self, document_id: str) -> object | None:
        with self._lock:
            return self._results.get(document_id)

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._results.pop(document_id, None)


analysis_store = AnalysisStore()


class DetectionStore:
    """
    Caches the last watermark-candidate list per document.
    """

    def __init__(self) -> None:
        self._results: dict[str, object] = {}
        self._lock = threading.Lock()

    def set(self, document_id: str, candidates: object) -> None:
        with self._lock:
            self._results[document_id] = candidates

    def get(self, document_id: str) -> object | None:
        with self._lock:
            return self._results.get(document_id)

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._results.pop(document_id, None)


detection_store = DetectionStore()


@dataclass
class JobProgress:
    document_id: str
    stage: str = "idle"  # "uploading" | "analyzing" | "detecting" | "processing" | "completed" | "error"
    current_page: int = 0
    total_pages: int = 0
    percent: int = 0
    message: str = ""
    candidates_count: int = 0
    failed_pages: list[int] = field(default_factory=list)
    error: str | None = None
    updated_at: datetime = field(default_factory=utcnow)


class ProgressStore:
    """
    Tracks live incremental progress for large documents (page-by-page progress).
    """

    def __init__(self) -> None:
        self._progress: dict[str, JobProgress] = {}
        self._lock = threading.Lock()

    def set(self, document_id: str, progress: JobProgress) -> None:
        with self._lock:
            progress.updated_at = utcnow()
            self._progress[document_id] = progress

    def update(
        self,
        document_id: str,
        stage: str | None = None,
        current_page: int | None = None,
        total_pages: int | None = None,
        message: str | None = None,
        candidates_count: int | None = None,
        failed_pages: list[int] | None = None,
        error: str | None = None,
    ) -> JobProgress:
        with self._lock:
            prog = self._progress.get(document_id)
            if prog is None:
                prog = JobProgress(document_id=document_id)
                self._progress[document_id] = prog
            if stage is not None:
                prog.stage = stage
            if current_page is not None:
                prog.current_page = current_page
            if total_pages is not None:
                prog.total_pages = total_pages
            if prog.total_pages > 0 and prog.current_page > 0:
                prog.percent = min(100, int((prog.current_page / prog.total_pages) * 100))
            if message is not None:
                prog.message = message
            if candidates_count is not None:
                prog.candidates_count = candidates_count
            if failed_pages is not None:
                prog.failed_pages = failed_pages
            if error is not None:
                prog.error = error
            prog.updated_at = utcnow()
            return prog

    def get(self, document_id: str) -> JobProgress | None:
        with self._lock:
            return self._progress.get(document_id)

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._progress.pop(document_id, None)


progress_store = ProgressStore()


class PreviewCache:
    _MAX_ENTRIES = 200

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, float], bytes] = {}
        self._order: list[tuple[str, int, float]] = []
        self._lock = threading.Lock()

    def get(self, document_id: str, page: int, mtime: float) -> bytes | None:
        with self._lock:
            return self._cache.get((document_id, page, mtime))

    def set(self, document_id: str, page: int, mtime: float, png_bytes: bytes) -> None:
        with self._lock:
            key = (document_id, page, mtime)
            if key not in self._cache and len(self._order) >= self._MAX_ENTRIES:
                oldest = self._order.pop(0)
                self._cache.pop(oldest, None)
            self._cache[key] = png_bytes
            self._order.append(key)

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            keys_to_remove = [key for key in self._cache if key[0] == document_id]
            for key in keys_to_remove:
                self._cache.pop(key, None)
                try:
                    self._order.remove(key)
                except ValueError:
                    pass


preview_cache = PreviewCache()
