import { FileText, UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { validatePdfClientSide } from "../utils/validateFile";

interface UploadAreaProps {
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

export function UploadArea({ onFileSelected, disabled }: UploadAreaProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (file: File) => {
      const validationError = validatePdfClientSide(file);
      if (validationError) {
        setLocalError(validationError);
        return;
      }
      setLocalError(null);
      onFileSelected(file);
    },
    [onFileSelected],
  );

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) handleFile(file);
    event.target.value = "";
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload PDF document"
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if ((event.key === "Enter" || event.key === " ") && !disabled) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
          disabled
            ? "cursor-not-allowed border-ink/10 bg-ink/[0.02] opacity-60"
            : isDragging
              ? "cursor-pointer border-accent bg-accent/5"
              : "cursor-pointer border-ink/20 hover:border-accent/60 hover:bg-ink/[0.02]"
        }`}
      >
        {isDragging ? (
          <FileText className="h-10 w-10 text-accent" aria-hidden="true" />
        ) : (
          <UploadCloud className="h-10 w-10 text-ink/40" aria-hidden="true" />
        )}
        <div>
          <p className="font-medium text-ink">Drop a PDF here, or click to browse</p>
          <p className="mt-1 text-sm text-ink/50">PDF only, up to 50MB</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="hidden"
          onChange={handleInputChange}
          disabled={disabled}
        />
      </div>
      {localError && (
        <p role="alert" className="mt-3 text-sm text-warn">
          {localError}
        </p>
      )}
    </div>
  );
}
