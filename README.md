# Document Cleaner

Privacy-first watermark removal for PDF documents you own or are authorized to modify.

> **Status: Phase 6** — upload, validation, temporary storage, structural PDF analysis, automatic
> text watermark removal (Case A), automatic image watermark removal (Case B), manual region selection
> for anything automatic detection can't see, and full scanned-PDF handling (Case C): watermark removal
> via OpenCV inpainting instead of destructive redaction, plus optional OCR to make scanned pages
> searchable. A richer in-app before/after preview lands in Phase 7 (see `Development Strategy` in the
> project spec).

## Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** FastAPI + Pydantic + PyMuPDF
- **Infra:** Docker + Docker Compose

## Project layout

```text
document-cleaner/
├── frontend/           React app (upload, analysis, detection, automatic & manual removal, OCR UI)
│   └── src/
│       ├── components/ UploadArea, ProgressBar, AnalysisSummary, CandidateList, ManualSelectionCanvas
│       ├── pages/      Home
│       ├── hooks/      useDocumentUpload, useDocumentAnalysis, useWatermarkDetection,
│       │               useWatermarkProcessing, useManualRemoval, useOcr
│       ├── services/   api.ts (backend client)
│       ├── types/      shared TS types
│       └── utils/      client-side validation helpers
├── backend/             FastAPI app
│   ├── app/
│   │   ├── main.py      app entrypoint, CORS, global error handler
│   │   ├── config.py     env-driven settings
│   │   ├── api/          documents.py (upload, analyze, status, detect, process, download,
│   │   │                 preview, manual-remove, ocr), health.py
│   │   ├── schemas/      Pydantic request/response models (document, analysis, watermark,
│   │   │                 processing, manual, ocr)
│   │   ├── services/     pdf_analyzer.py, watermark_detector.py, text_remover.py, image_remover.py,
│   │   │                 watermark_remover.py, manual_remover.py, scanned_detector.py, inpainting.py,
│   │   │                 ocr_service.py
│   │   └── utils/        file validation, in-memory document/analysis/detection stores
│   └── tests/           pytest suite: upload validation, analysis, text + image watermark
│                         detection & removal, manual selection, scanned-page inpainting + OCR
├── docker-compose.yml
├── .env.example
└── .gitignore
```

## Prerequisites

- Node.js 20+
- Python 3.14 (3.12+ also works — dependency versions are pinned to releases with
  published wheels for 3.12, 3.13, and 3.14, so no source builds are required)
- **Tesseract OCR** (system binary, not a Python package) — needed for the `/ocr` endpoint.
  - Ubuntu/Debian: `sudo apt install tesseract-ocr tesseract-ocr-eng`
  - Windows: install from https://github.com/UB-Mannheim/tesseract/wiki and ensure `tesseract.exe`
    is on your `PATH` (or set `pytesseract.pytesseract.tesseract_cmd` if not)
  - Everything else (removal, detection, analysis, manual selection) works without it — OCR is the
    only feature that needs the binary present.
- Docker Desktop (optional, for the containerized run — the backend image installs Tesseract for you)

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

## Testing the full upload → detect → remove → manual select → OCR → download flow

1. With both servers running, open `http://localhost:5173`.
2. Drag a PDF onto the upload area, or click to browse.
3. Upload, analysis, and watermark detection run automatically in sequence.
4. Detected candidates appear as a checklist (pre-selected, confidence-labeled) — uncheck any you don't want removed.
5. Click **Remove selected watermark(s)**.
6. If anything is still visible afterward (e.g. a vector-drawn logo automatic detection can't see, or
   a watermark baked into a scanned page), click **"Still see a watermark? Select it manually"**, drag
   a box over it on the rendered page preview, and click **Remove selected area(s)**. On a scanned
   page this restores the area with inpainting instead of leaving a blank patch. Check "Apply this
   selection to all pages" to repeat the same box on every page.
7. If the analysis found the document looks scanned, an option to **"Make this document searchable
   (OCR)"** appears — click it to add a searchable text layer (the page's appearance doesn't change).
8. Click **Download cleaned PDF**.

Or via curl:

```powershell
curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@sample.pdf;type=application/pdf"
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/detect
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/process ^
  -H "Content-Type: application/json" ^
  -d "{\"candidate_ids\": [\"<candidate_id>\"], \"pages\": \"all\"}"

REM see the page to pick a manual region, then remove it (fractional 0-1 coordinates)
REM — automatically inpainted instead of redacted if that page is scanned
curl -o page1.png http://localhost:8000/api/v1/documents/<document_id>/preview/1
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/manual-remove ^
  -H "Content-Type: application/json" ^
  -d "{\"regions\": [{\"page\": 1, \"x0\": 0.05, \"y0\": 0.85, \"x1\": 0.15, \"y1\": 0.92}], \"apply_to_all_pages\": true}"

REM add a searchable text layer to scanned pages (omit "pages" to auto-target every scanned page)
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/ocr -H "Content-Type: application/json" -d "{}"

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

## How scanned-page handling works (Case C)

- **The problem, confirmed directly:** on a scanned page, the "image" *is* the page's content — one
  raster covering the whole page. Redacting even a small region that only partially overlaps that
  image doesn't trim the overlap out; it deletes the **entire image object**. A watermark stamp in
  one corner would take the whole scanned page down with it.
- **The fix (`inpainting.py` + `manual_remover.py`):** manual selection now checks whether the target
  page is scanned (`scanned_detector.py`, reusing Phase 2's `is_scanned` flag plus the dominant
  image's xref). Scanned pages route to a different path entirely: extract the original-resolution
  embedded image, build a mask from the selected region(s), run OpenCV's classical Telea inpainting
  (`cv2.INPAINT_TELEA` — not a learned/generative model, keeping this free of AI dependencies for core
  functionality), and write the restored image back to the *same* xref via `page.replace_image()` — so
  everything else about the page is untouched. Normal pages still use Phase 5's redaction path
  unchanged.
- **OCR (`ocr_service.py`):** optional and page-scoped — only pages the analyzer flagged as scanned are
  touched, so a document that already has a real text layer is left alone even if OCR is requested for
  the whole thing. Implemented directly via pytesseract (Tesseract's Python binding) plus PyMuPDF's
  invisible-text insertion (`render_mode=3`) at each recognized word's position, rather than shelling
  out to `ocrmypdf`/Ghostscript/qpdf — same OCR engine, lighter toolchain. Verified the invisible layer
  doesn't create a visible duplicate by rendering before/after and confirming pixel output is
  unchanged.
- **A second xref-staleness bug, caught before shipping:** cached analysis (with its embedded image
  xrefs) goes stale after *any* prior save, since PyMuPDF's garbage-collecting save renumbers PDF
  objects document-wide — even for pages that save didn't touch. Manual removal's scanned-page lookup
  now always re-analyzes the exact bytes it's about to inpaint, rather than trusting a cached value
  that might refer to a different object than intended.

## What Phase 6 does NOT do yet

- No side-by-side before/after comparison view — the page preview used for manual selection doubles
  as a way to inspect the current state, but a dedicated before/after UI is Phase 7 work
- No background job queue (Redis/Celery) — not needed yet; processing is synchronous and fast enough
  for MVP PDFs (OCR is the slowest step, so its API call uses a longer client-side timeout)
- No database — an in-memory store tracks documents, analysis, and detected candidates for this process's lifetime only
- OCR currently only bundles the English Tesseract language pack in the Docker image; other languages
  need their `tesseract-ocr-<lang>` package added to the Dockerfile

## Security & privacy notes

- Every upload is validated by extension, size, and PDF magic bytes — never trusted on content-type header alone.
- Stored files use server-generated UUIDs; the original filename is never used to build a filesystem path.
  The download filename is derived from the original name but sanitized to a safe character set.
- Password-protected PDFs are rejected at upload, and re-checked at analysis and processing time — the
  app does not attempt to bypass passwords or encryption.
- Analysis and detection are done via PyMuPDF's object-level extraction, not by rasterizing the page.
  Automatic removal uses text- and image-scoped redaction only and never rewrites vector graphics;
  manual removal is scoped to exactly the box the user drew, using inpainting (not deletion) on
  scanned pages specifically to avoid destroying page content.
- The preview endpoint renders a page to a PNG server-side; it never modifies the document, only reads it.
- OCR runs entirely locally via Tesseract — no page content or extracted text is sent to any external
  service.
- CORS is restricted to the configured frontend origin (never `*`).
- Internal errors are logged server-side only; the client always receives a generic, safe error message.
- Uploaded and processed files are not yet auto-deleted — the cleanup worker described in the spec is a later phase.
