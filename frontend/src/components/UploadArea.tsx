import { FileText, FolderUp, Sparkles, UploadCloud } from "lucide-react";
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
    <div className="w-full">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload PDF or PowerPoint document"
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
        className={`relative flex flex-col items-center justify-center gap-5 rounded-3xl border-2 border-dashed p-10 text-center transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
          disabled
            ? "cursor-not-allowed border-slate-200 bg-slate-50/50 opacity-60"
            : isDragging
              ? "cursor-pointer border-brand-500 bg-brand-50/40 shadow-xl shadow-brand-500/10 scale-[1.005]"
              : "cursor-pointer border-brand-300 bg-white hover:border-brand-500 hover:bg-brand-50/20 shadow-xl shadow-brand-500/5"
        }`}
      >
        {/* Top-Right Badge matching screenshot 2 */}
        <div className="absolute top-5 right-5 hidden sm:flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-[11px] font-semibold text-amber-700 border border-amber-200">
          <Sparkles className="h-3 w-3 text-amber-500" />
          Official Tool Engine
        </div>

        {/* Central Icon */}
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-tr from-brand-700 to-brand-500 text-white shadow-lg shadow-brand-500/25">
          {isDragging ? (
            <FileText className="h-8 w-8 animate-bounce" aria-hidden="true" />
          ) : (
            <UploadCloud className="h-8 w-8" aria-hidden="true" />
          )}
        </div>

        {/* Header Text */}
        <div className="space-y-1">
          <h2 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
            Drag and Drop Your File Here <span className="text-brand-600">↗</span>
          </h2>
          <p className="text-xs text-slate-500 sm:text-sm max-w-md mx-auto">
            Drag and drop any PDF or PowerPoint (.pptx) file, or click below to launch
          </p>
        </div>

        {/* Big Action Button */}
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          onClick={(e) => {
            e.stopPropagation();
            if (!disabled) inputRef.current?.click();
          }}
          className="inline-flex items-center gap-2.5 rounded-2xl bg-gradient-to-r from-brand-600 to-brand-500 px-7 py-3.5 text-sm font-semibold text-white shadow-lg shadow-brand-500/25 transition-all hover:from-brand-700 hover:to-brand-600 hover:shadow-xl hover:shadow-brand-500/30 hover:scale-[1.02] active:scale-[0.98]"
        >
          <FolderUp className="h-4 w-4" />
          Drag and Drop Your File
        </button>

        {/* File Types & Size Constraints */}
        <p className="text-[11px] text-slate-400 font-medium">
          PDF & PPTX supported • Up to 50MB • Free & Private
        </p>

        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.pptx,.ppt,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation"
          className="hidden"
          onChange={handleInputChange}
          disabled={disabled}
        />
      </div>

      {localError && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-center text-sm font-medium text-red-700 shadow-sm">
          {localError}
        </div>
      )}
    </div>
  );
}
