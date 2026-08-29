"""
Minimal in-memory document registry for the Phase 1 MVP.

This intentionally avoids introducing PostgreSQL/Redis until the
project actually needs them (see project rule: don't add services
before they're necessary). This store is process-local and is lost
on restart — acceptable for MVP since documents are temporary anyway.

Replace with a real persistence layer only once background workers
or multi-process deployment make an in-memory dict insufficient.
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

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._records.pop(document_id, None)

    def all_older_than(self, cutoff: datetime) -> list[DocumentRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.uploaded_at < cutoff]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Process-wide singleton for the MVP.
document_store = DocumentStore()


class AnalysisStore:
    """
    Caches the last analysis result per document so the frontend can
    re-fetch it (e.g. GET .../status) without re-running PyMuPDF.
    Same process-local, in-memory tradeoff as DocumentStore.
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
    Caches the last watermark-candidate list per document, so /process
    can look up candidates by ID without re-running detection.
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


class PreviewCache:
    """
    Caches rendered page-preview PNGs. Keyed by (document_id, page,
    file mtime) so a cache entry automatically becomes unreachable
    the moment the underlying file changes (any removal step
    rewrites result_path with a new mtime) — no manual invalidation
    needed. Capped to avoid unbounded growth across many documents.
    """

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


preview_cache = PreviewCache()
