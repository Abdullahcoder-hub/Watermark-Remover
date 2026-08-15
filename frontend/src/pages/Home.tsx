import { CheckCircle2, Loader2, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect } from "react";

import { AnalysisSummary } from "../components/AnalysisSummary";
import { ProgressBar } from "../components/ProgressBar";
import { UploadArea } from "../components/UploadArea";
import { useDocumentAnalysis } from "../hooks/useDocumentAnalysis";
import { useDocumentUpload } from "../hooks/useDocumentUpload";
import { formatFileSize } from "../utils/validateFile";

export function Home() {
  const { status, progress, result, errorMessage, upload, reset: resetUpload } = useDocumentUpload();
  const { status: analysisStatus, result: analysis, errorMessage: analysisError, analyze, reset: resetAnalysis } = useDocumentAnalysis();

  // Workflow: Upload -> Validate -> Analyze. Once the upload succeeds,
  // automatically kick off analysis for that document.
  useEffect(() => {
    if (status === "success" && result) {
      analyze(result.document_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, result]);

  const reset = () => {
    resetUpload();
    resetAnalysis();
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col px-6 py-16">
      <header className="mb-12 text-center">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1 text-xs font-medium text-accent">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
          Private document processing
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Remove watermarks from your documents</h1>
        <p className="mt-3 text-ink/60">Upload &rarr; Detect &rarr; Review &rarr; Clean. Files are processed locally and deleted automatically.</p>
      </header>

      <main className="flex-1">
        {status === "idle" || status === "uploading" ? (
          <>
            <UploadArea onFileSelected={upload} disabled={status === "uploading"} />
            {status === "uploading" && (
              <div className="mt-6">
                <ProgressBar percent={progress} label={`Uploading… ${progress}%`} />
              </div>
            )}
          </>
        ) : null}

        {status === "error" && (
          <div className="mt-6 rounded-xl border border-warn/30 bg-warn/5 p-6">
            <p className="font-medium text-warn">We couldn't upload this document.</p>
            <p className="mt-1 text-sm text-ink/70">{errorMessage}</p>
            <button
              type="button"
              onClick={reset}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Try another file
            </button>
          </div>
        )}

        {status === "success" && result && (
          <div className="mt-6 rounded-xl border border-accent/30 bg-accent/5 p-6">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden="true" />
              <div>
                <p className="font-medium text-ink">Uploaded successfully</p>
                <dl className="mt-2 space-y-1 text-sm text-ink/70">
                  <div className="flex gap-2">
                    <dt className="text-ink/50">File:</dt>
                    <dd>{result.original_filename}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Size:</dt>
                    <dd>{formatFileSize(result.size_bytes)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Pages:</dt>
                    <dd>{result.page_count ?? "—"}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink/50">Document ID:</dt>
                    <dd className="font-mono text-xs">{result.document_id}</dd>
                  </div>
                </dl>
              </div>
            </div>

            {analysisStatus === "analyzing" && (
              <div className="mt-4 flex items-center gap-2 text-sm text-ink/60">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Analyzing document…
              </div>
            )}

            {analysisStatus === "error" && (
              <div className="mt-4 rounded-lg bg-warn/5 p-3 text-sm text-warn">
                Analysis failed: {analysisError}
              </div>
            )}

            {analysisStatus === "success" && analysis && <AnalysisSummary analysis={analysis} />}

            <button
              type="button"
              onClick={reset}
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-ink/15 px-4 py-2 text-sm font-medium text-ink hover:bg-ink/5 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Upload another document
            </button>
          </div>
        )}
      </main>

      <footer className="mt-16 text-center text-xs text-ink/40">
        For documents you own or are authorized to modify. Files are deleted automatically after processing.
      </footer>
    </div>
  );
}
