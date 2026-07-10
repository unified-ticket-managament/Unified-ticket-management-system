import { useRef, useState } from "react";
import { UploadCloud, X } from "lucide-react";
import { Button } from "@tw/components/common/Button";
import {
  ATTACHMENT_ACCEPT_ATTR,
  MAX_ATTACHMENT_FILES,
  formatBytes,
  iconForFilename,
  validateFiles,
} from "@tw/lib/attachmentMeta";

interface FileDropzoneProps {
  label: string;
  hint?: string;
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
}

function dedupeKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function FileDropzone({
  label,
  hint = "Up to 10 files, 25 MB each. PDF, Office, images, or text.",
  files,
  onFilesChange,
  disabled = false,
}: FileDropzoneProps) {
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
      <span className="mb-1.5 block text-xs font-semibold text-slate-600">{label}</span>

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
        className={`flex flex-col items-center gap-2 rounded-md2 border border-dashed px-4 py-6 text-center transition-colors ${
          isDragOver ? "border-accent bg-accent/5" : "border-border bg-canvas/50"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <UploadCloud size={20} className="text-muted" />
        <p className="text-[12px] text-muted">Drag files here, or</p>
        <Button
          variant="secondary"
          size="sm"
          type="button"
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
      </div>

      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{hint}</span>}

      {errors.length > 0 && (
        <div className="mt-2 flex flex-col gap-1 rounded-md2 border border-danger/20 bg-danger/5 px-3 py-2">
          {errors.map((error) => (
            <p key={error} className="text-[11px] text-danger">
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
                className="flex items-center gap-2.5 rounded-md2 border border-border bg-surface px-3 py-1.5"
              >
                <Icon size={14} className="flex-none text-muted" />
                <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-700">
                  {file.name}
                </span>
                <span className="flex-none text-[11px] text-muted">{formatBytes(file.size)}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  className="!px-1.5 !py-1"
                  disabled={disabled}
                  onClick={() => removeFile(file)}
                  aria-label={`Remove ${file.name}`}
                >
                  <X size={12} />
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
