"use client";

import { useRef, useState } from "react";
import { UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ATTACHMENT_ACCEPT_ATTR,
  MAX_ATTACHMENT_FILES,
  formatBytes,
  iconForFilename,
  validateFiles,
} from "@tw/lib/attachmentMeta";

interface AttachmentUploaderProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
}

function dedupeKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

// Shared drag-and-drop + browse + preview + remove attachment picker
// for both the Compose screen and the inline Reply composer —
// PDF/DOC/DOCX/XLSX/CSV/PNG/JPG/JPEG/ZIP, up to 10 files / 25MB each
// (see lib/attachmentMeta.ts, which mirrors the backend's own
// allow-list).
export function AttachmentUploader({ files, onFilesChange, disabled = false }: AttachmentUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  function addFiles(incoming: FileList | File[]) {
    const existingKeys = new Set(files.map(dedupeKey));
    const newFiles = Array.from(incoming).filter((f) => !existingKeys.has(dedupeKey(f)));
    const { accepted, errors: validationErrors } = validateFiles([...files, ...newFiles]);
    setErrors(validationErrors);
    onFilesChange(accepted);
  }

  function removeFile(file: File) {
    onFilesChange(files.filter((f) => f !== file));
    setErrors([]);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          if (!disabled && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-5 text-center transition-colors",
          isDragOver ? "border-primary bg-primary/5" : "border-border bg-muted/30",
          disabled && "pointer-events-none opacity-50"
        )}
      >
        <UploadCloud className="h-5 w-5 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">Drag files here, or</p>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={disabled || files.length >= MAX_ATTACHMENT_FILES}
          onClick={() => inputRef.current?.click()}
        >
          Browse files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPT_ATTR}
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            if (e.target.files?.length) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-[11px] text-muted-foreground/80">
          PDF, DOC, DOCX, XLSX, CSV, PNG, JPG, JPEG, ZIP — up to {MAX_ATTACHMENT_FILES} files, 25MB each.
        </p>
      </div>

      {errors.length > 0 && (
        <div className="mt-2 flex flex-col gap-1 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2">
          {errors.map((error) => (
            <p key={error} className="text-[11px] text-destructive">
              {error}
            </p>
          ))}
        </div>
      )}

      {files.length > 0 && (
        <ul className="mt-2.5 flex flex-col gap-1.5">
          {files.map((file) => {
            const Icon = iconForFilename(file.name);
            return (
              <li
                key={dedupeKey(file)}
                className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-1.5"
              >
                <Icon className="h-3.5 w-3.5 flex-none text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">{file.name}</span>
                <span className="flex-none text-[11px] text-muted-foreground">{formatBytes(file.size)}</span>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => removeFile(file)}
                  aria-label={`Remove ${file.name}`}
                  className="flex-none rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
