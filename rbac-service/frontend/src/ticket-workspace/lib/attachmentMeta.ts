import { Archive, FileSpreadsheet, FileText, Image, File as FileIcon, type LucideIcon } from "lucide-react";
import type { AttachmentMeta } from "@tw/types";

export const MAX_ATTACHMENT_FILES = 10;
export const MAX_ATTACHMENT_SIZE_BYTES = 25 * 1024 * 1024;

export const ALLOWED_ATTACHMENT_EXTENSIONS = [
  "pdf",
  "doc",
  "docx",
  "xls",
  "xlsx",
  "csv",
  "png",
  "jpg",
  "jpeg",
  "gif",
  "txt",
  "zip",
];

export const ATTACHMENT_ACCEPT_ATTR = ALLOWED_ATTACHMENT_EXTENSIONS.map((ext) => `.${ext}`).join(",");

const ICON_BY_EXTENSION: Record<string, LucideIcon> = {
  pdf: FileText,
  doc: FileText,
  docx: FileText,
  txt: FileText,
  xls: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  csv: FileSpreadsheet,
  png: Image,
  jpg: Image,
  jpeg: Image,
  gif: Image,
  zip: Archive,
};

function extensionOf(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

export function iconForFilename(filename: string): LucideIcon {
  return ICON_BY_EXTENSION[extensionOf(filename)] ?? FileIcon;
}

export function isImageAttachment(attachment: Pick<AttachmentMeta, "mime_type" | "filename">): boolean {
  if (attachment.mime_type) return attachment.mime_type.startsWith("image/");
  return ["png", "jpg", "jpeg", "gif"].includes(extensionOf(attachment.filename));
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface FileValidationResult {
  accepted: File[];
  errors: string[];
}

export function validateFiles(files: File[]): FileValidationResult {
  const errors: string[] = [];
  const accepted: File[] = [];

  if (files.length > MAX_ATTACHMENT_FILES) {
    errors.push(`Only ${MAX_ATTACHMENT_FILES} files can be attached at once.`);
  }

  const withinLimit = files.slice(0, MAX_ATTACHMENT_FILES);

  for (const file of withinLimit) {
    const extension = extensionOf(file.name);

    if (!ALLOWED_ATTACHMENT_EXTENSIONS.includes(extension)) {
      errors.push(`"${file.name}" has an unsupported file type.`);
      continue;
    }

    if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
      errors.push(`"${file.name}" exceeds the 25MB size limit.`);
      continue;
    }

    accepted.push(file);
  }

  return { accepted, errors };
}
