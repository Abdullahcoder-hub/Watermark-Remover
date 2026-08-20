# Document Cleaner

Privacy-first watermark removal for PDF documents you own or are authorized to modify.

> **Status: Phase 5** — upload, validation, temporary storage, structural PDF analysis, automatic
> text watermark removal (Case A), automatic image watermark removal (Case B), and manual region
> selection for anything automatic detection can't see (e.g. vector-drawn logos). Scanned-PDF/OCR
> handling and a richer in-app before/after preview land in later phases (see `Development Strategy`
> in the project spec).

## Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** FastAPI + Pydantic + PyMuPDF
- **Infra:** Docker + Docker Compose

## Project layout

```text
document-cleaner/
├── frontend/           React app (upload, analysis, detection, automatic & manual removal UI)
│   └── src/
│       ├── components/ UploadArea, ProgressBar, AnalysisSummary, CandidateList, ManualSelectionCanvas
│       ├── pages/      Home
│       ├── hooks/      useDocumentUpload, useDocumentAnalysis, useWatermarkDetection,
│       │               useWatermarkProcessing, useManualRemoval
│       ├── services/   api.ts (backend client)
│       ├── types/      shared TS types
│       └── utils/      client-side validation helpers
├── backend/             FastAPI app
│   ├── app/
│   │   ├── main.py      app entrypoint, CORS, global error handler
│   │   ├── config.py     env-driven settings
│   │   ├── api/          documents.py (upload, analyze, status, detect, process, download,
│   │   │                 preview, manual-remove), health.py
│   │   ├── schemas/      Pydantic request/response models (document, analysis, watermark,
│   │   │                 processing, manual)
│   │   ├── services/     pdf_analyzer.py, watermark_detector.py, text_remover.py, image_remover.py,
│   │   │                 watermark_remover.py, manual_remover.py
│   │   └── utils/        file validation, in-memory document/analysis/detection stores
│   └── tests/           pytest suite: upload validation, analysis, text + image watermark
│                         detection & removal, manual selection
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

## Testing the full upload → detect → remove → manual select → download flow

1. With both servers running, open `http://localhost:5173`.
2. Drag a PDF onto the upload area, or click to browse.
3. Upload, analysis, and watermark detection run automatically in sequence.
4. Detected candidates appear as a checklist (pre-selected, confidence-labeled) — uncheck any you don't want removed.
5. Click **Remove selected watermark(s)**.
6. If anything is still visible afterward (e.g. a vector-drawn logo automatic detection can't see),
   click **"Still see a watermark? Select it manually"**, drag a box over it on the rendered page
   preview, and click **Remove selected area(s)**. Check "Apply this selection to all pages" to
   repeat the same box on every page.
7. Click **Download cleaned PDF**.

Or via curl:

```powershell
curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@sample.pdf;type=application/pdf"
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/detect
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/process ^
  -H "Content-Type: application/json" ^
  -d "{\"candidate_ids\": [\"<candidate_id>\"], \"pages\": \"all\"}"

REM see the page to pick a manual region, then remove it (fractional 0-1 coordinates)
curl -o page1.png http://localhost:8000/api/v1/documents/<document_id>/preview/1
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/manual-remove ^
  -H "Content-Type: application/json" ^
  -d "{\"regions\": [{\"page\": 1, \"x0\": 0.05, \"y0\": 0.85, \"x1\": 0.15, \"y1\": 0.92}], \"apply_to_all_pages\": true}"

curl -o cleaned.pdf http://localhost:8000/api/v1/documents/<document_id>/download
```

Or run the automated backend tests:

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

## How detection and removal work

- **Text detection** (`watermark_detector.py`) scores each text object from Phase 2's analysis using
  four weighted signals: repeated across multiple pages (+0.4), rotated (+0.3), matches common
  watermark wording like "CONFIDENTIAL"/"DRAFT"/"SAMPLE"/"CamScanner" (+0.2), and large relative to
  the page (+0.1).
- **Image detection** (same module) scores each embedded image using four analogous signals: the same
  image (same PDF xref) reused across multiple pages (+0.4), has transparency/alpha (+0.3, typical of
  watermark overlays), moderate size relative to the page (+0.2), and roughly centered (+0.1). Full-page
  images are excluded entirely — those are Phase 2's "scanned page" content, not a watermark overlay.
  Nothing is removed automatically for either type — every candidate, however high its confidence,
  waits for the user to select it.
- **Automatic removal** (`watermark_remover.py`) removes a mixed list of text and image candidates in
  a single PyMuPDF document pass — add every redaction (text quads, image rects) per page, apply once
  per page, save once at the end. Text removal never touches images (`images=PDF_REDACT_IMAGE_NONE`)
  and image removal never touches text (`text=PDF_REDACT_TEXT_NONE`); vector graphics are always left
  alone (`graphics=PDF_REDACT_LINE_ART_NONE`). This matches the spec's Case A and Case B requirement to
  remove only the watermark object while preserving the rest of the document.
- **Manual removal** (`manual_remover.py`) is deliberately blunt: within a user-drawn box, everything
  is removed — text, raster images, *and* vector graphics (`graphics=PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED`).
  This exists specifically because some watermarks are structurally invisible to automatic detection —
  confirmed directly: a CamScanner-style watermark icon drawn with vector paths (`page.new_shape()`,
  no PDF xref) produces zero image candidates no matter how the image detector's thresholds are tuned,
  because it isn't an image object at all. Manual selection is the only way to remove it, and it
  works regardless of what kind of object is actually there.
- **A page preview endpoint** (`GET /{id}/preview/{page}`, renders via PyMuPDF at 150 DPI) exists so
  the user has something to draw on — this is a minimal version of what Phase 7's fuller before/after
  preview will build on.
- **Automatic and manual removal compose correctly**: both `/process` and `/manual-remove` operate on
  the document's *current* state (its already-processed result if one exists, otherwise the original
  upload) via a shared `_current_source_path()` helper, so running one after the other layers edits
  instead of one silently discarding the other's work.
- **Why a single pass, not two, within automatic removal:** an earlier version chained
  `remove_text_candidates()` into `remove_image_candidates()` by feeding the first step's output into
  the second. This was verified to corrupt image removal: PyMuPDF's garbage-collecting save renumbers
  PDF object xrefs, so an image candidate's xref (captured at detection time) silently pointed at the
  wrong object after the intermediate save. Doing both removals against the same open document, before
  any save happens, eliminates the issue rather than working around it.
- **Known limitation:** PyMuPDF's text redaction overlap test uses the axis-aligned bounding box of the
  removed region, not its exact rotated shape. A steeply rotated or oversized watermark whose bounding
  box happens to sweep over nearby body text can take that text with it. This is inherent to
  rectangular/quad-based redaction. Manual selection's page preview lets you spot this before
  downloading; a richer before/after comparison view is still Phase 7 work.

## What Phase 5 does NOT do yet

- No scanned-PDF / OCR / image restoration (Phase 6) — manual selection on a scanned page will still
  delete pixels from within the box, but there's no inpainting to fill the gap naturally
- No side-by-side before/after comparison view — the page preview used for manual selection doubles
  as a way to inspect the current state, but a dedicated before/after UI is Phase 7
  work
- No background job queue (Redis/Celery) — not needed yet; processing is synchronous and fast enough for MVP PDFs
- No database — an in-memory store tracks documents, analysis, and detected candidates for this process's lifetime only

## Security & privacy notes

- Every upload is validated by extension, size, and PDF magic bytes — never trusted on content-type header alone.
- Stored files use server-generated UUIDs; the original filename is never used to build a filesystem path.
  The download filename is derived from the original name but sanitized to a safe character set.
- Password-protected PDFs are rejected at upload, and re-checked at analysis and processing time — the
  app does not attempt to bypass passwords or encryption.
- Analysis and detection are done via PyMuPDF's object-level extraction, not by rasterizing the page.
  Automatic removal uses text- and image-scoped redaction only and never rewrites vector graphics;
  manual removal is scoped to exactly the box the user drew.
- The preview endpoint renders a page to a PNG server-side; it never modifies the document, only reads it.
- CORS is restricted to the configured frontend origin (never `*`).
- Internal errors are logged server-side only; the client always receives a generic, safe error message.
- Uploaded and processed files are not yet auto-deleted — the cleanup worker described in the spec is a later phase.
