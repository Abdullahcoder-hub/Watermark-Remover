# Document Cleaner

Privacy-first watermark removal for PDF documents you own or are authorized to modify.

> **Status: Phase 2** — upload, validation, temporary storage, and structural PDF analysis
> (text extraction, image detection, scanned-page detection).
> Watermark detection/scoring and removal land in later phases (see `Development Strategy` in the project spec).

## Stack

- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Backend:** FastAPI + Pydantic + PyMuPDF
- **Infra:** Docker + Docker Compose

## Project layout

```text
document-cleaner/
├── frontend/           React app (upload + analysis UI)
│   └── src/
│       ├── components/ UploadArea, ProgressBar, AnalysisSummary
│       ├── pages/      Home
│       ├── hooks/      useDocumentUpload, useDocumentAnalysis
│       ├── services/   api.ts (backend client)
│       ├── types/      shared TS types
│       └── utils/      client-side validation helpers
├── backend/             FastAPI app
│   ├── app/
│   │   ├── main.py      app entrypoint, CORS, global error handler
│   │   ├── config.py     env-driven settings
│   │   ├── api/          documents.py (upload, analyze, status), health.py
│   │   ├── schemas/      Pydantic request/response models (document, analysis)
│   │   ├── services/     pdf_analyzer.py (text/image extraction, scanned detection)
│   │   └── utils/        file validation, in-memory document + analysis stores
│   └── tests/           pytest suite: upload validation + analysis
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

## Testing the upload and analysis

1. With both servers running, open `http://localhost:5173`.
2. Drag a PDF onto the upload area, or click to browse.
3. You should see a progress bar, then a success card with the document ID, size, and page count.
4. Analysis kicks off automatically and shows text object count, image count, and whether the document appears scanned.

Or via curl:

```powershell
curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@sample.pdf;type=application/pdf"
curl -X POST http://localhost:8000/api/v1/documents/<document_id>/analyze
curl http://localhost:8000/api/v1/documents/<document_id>/status
```

Or run the automated backend tests:

```powershell
cd backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

## What Phase 2 does NOT do yet

- No watermark candidate scoring — analysis reports raw text/image structure only, not which of it might be a watermark
- No processing/removal
- No before/after preview
- No download endpoint
- No manual region selection
- No background job queue (Redis/Celery) — not needed until processing is added
- No database — an in-memory store tracks uploaded documents and their analysis results for this process's lifetime only

## Security & privacy notes

- Every upload is validated by extension, size, and PDF magic bytes — never trusted on content-type header alone.
- Stored files use server-generated UUIDs; the original filename is never used to build a filesystem path.
- Password-protected PDFs are rejected at upload and re-checked at analysis time — the app does not attempt to bypass passwords or encryption.
- Analysis is done via PyMuPDF's object-level text/image extraction, not by rasterizing the page, so it doesn't touch document content beyond reading it.
- CORS is restricted to the configured frontend origin (never `*`).
- Internal errors are logged server-side only; the client always receives a generic, safe error message.
- Uploaded files are not yet auto-deleted — the cleanup worker described in the spec is a later phase.
