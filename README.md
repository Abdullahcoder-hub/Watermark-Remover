# Document Cleaner

Privacy-first watermark removal for PDF documents you own or are authorized to modify.

> **Status: Phase 3** — upload, validation, temporary storage, structural PDF analysis,
> and text watermark detection + removal (Case A: separate PDF text objects).
> Image watermark removal, scanned-PDF/OCR handling, and manual selection land in later phases
> (see `Development Strategy` in the project spec).

## Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** FastAPI + Pydantic + PyMuPDF
- **Infra:** Docker + Docker Compose

## Project layout

```text
document-cleaner/
├── frontend/           React app (upload, analysis, detection & removal UI)
│   └── src/
│       ├── components/ UploadArea, ProgressBar, AnalysisSummary, CandidateList
│       ├── pages/      Home
│       ├── hooks/      useDocumentUpload, useDocumentAnalysis, useWatermarkDetection, useWatermarkProcessing
│       ├── services/   api.ts (backend client)
│       ├── types/      shared TS types
│       └── utils/      client-side validation helpers
├── backend/             FastAPI app
│   ├── app/
│   │   ├── main.py      app entrypoint, CORS, global error handler
│   │   ├── config.py     env-driven settings
│   │   ├── api/          documents.py (upload, analyze, status, detect, process, download), health.py
│   │   ├── schemas/      Pydantic request/response models (document, analysis, watermark, processing)
│   │   ├── services/     pdf_analyzer.py, watermark_detector.py, text_remover.py
│   │   └── utils/        file validation, in-memory document/analysis/detection stores
│   └── tests/           pytest suite: upload validation, analysis, watermark detection + removal
├── docker-compose.yml
├── .env.example
└── .gitignore
```

## Prerequisites

- Node.js 20+
- Python 3.14 (3.12+ also works — dependency versions are pinned to releases with
  published wheels for 3.12, 3.13, and 3.14, so no source builds are required)
- Docker Desktop (optional, for the containerized run — the backend image uses `python:3.14-slim`)

## Setup — Windows

Open PowerShell in the project root (`document-cleaner\`).

### Backend

```powershell
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend

Open a second PowerShell window:

```powershell
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

### Run with Docker instead

```powershell
copy .env.example .env
docker compose up --build
```

## Testing the full upload → detect → remove → download flow

1. With both servers running, open `http://localhost:5173`.
2. Drag a PDF onto the upload area, or click to browse.
3. Upload, analysis, and watermark detection run automatically in sequence.
4. Detected candidates appear as a checklist (pre-selected, confidence-labeled) — uncheck any you don't want removed.
5. Click **Remove selected watermark(s)**, then **Download cleaned PDF**.

Or via curl:

```powershell
curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@sample.pdf;type=application/pdf"
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/detect
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/process ^
  -H "Content-Type: application/json" ^
  -d "{\"candidate_ids\": [\"<candidate_id>\"], \"pages\": \"all\"}"
curl -o cleaned.pdf http://localhost:8000/api/v1/documents/<document_id>/download
```

Or run the automated backend tests:

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

## How detection and removal work

- **Detection** (`watermark_detector.py`) scores each text object from Phase 2's analysis using four
  weighted signals: repeated across multiple pages (+0.4), rotated (+0.3), matches common watermark
  wording like "CONFIDENTIAL"/"DRAFT"/"SAMPLE" (+0.2), and large relative to the page (+0.1). Nothing
  is removed automatically — every candidate, however high its confidence, waits for the user to select it.
- **Removal** (`text_remover.py`) uses PyMuPDF's redaction API restricted to text only
  (`images=PDF_REDACT_IMAGE_NONE`, `graphics=PDF_REDACT_LINE_ART_NONE`), so images and vector graphics
  on the page are never touched — matching the spec's Case A requirement to remove the watermark object
  while preserving the rest of the document.
- **Known limitation:** PyMuPDF's redaction overlap test uses the axis-aligned bounding box of the
  removed region, not its exact rotated shape. A steeply rotated or oversized watermark whose bounding
  box happens to sweep over nearby body text can take that text with it. This is inherent to
  rectangular/quad-based redaction. The upcoming preview phase will let users visually confirm the
  result before downloading.

## What Phase 3 does NOT do yet

- No image watermark detection/removal (Phase 4)
- No manual region selection (Phase 5)
- No scanned-PDF / OCR / image restoration (Phase 6)
- No in-app before/after preview — you have to download to inspect the result (Phase 7 adds this)
- No background job queue (Redis/Celery) — not needed yet; processing is synchronous and fast enough for MVP PDFs
- No database — an in-memory store tracks documents, analysis, and detected candidates for this process's lifetime only

## Security & privacy notes

- Every upload is validated by extension, size, and PDF magic bytes — never trusted on content-type header alone.
- Stored files use server-generated UUIDs; the original filename is never used to build a filesystem path.
  The download filename is derived from the original name but sanitized to a safe character set.
- Password-protected PDFs are rejected at upload, and re-checked at analysis and processing time — the
  app does not attempt to bypass passwords or encryption.
- Analysis and detection are done via PyMuPDF's object-level extraction, not by rasterizing the page.
  Removal uses text-only redaction and never rewrites images or vector graphics.
- CORS is restricted to the configured frontend origin (never `*`).
- Internal errors are logged server-side only; the client always receives a generic, safe error message.
- Uploaded and processed files are not yet auto-deleted — the cleanup worker described in the spec is a later phase.
