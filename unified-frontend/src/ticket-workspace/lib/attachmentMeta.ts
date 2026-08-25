import {
  Archive,
  FileSpreadsheet,
  FileText,
  Image,
  Music,
  Video,
  File as FileIcon,
  type LucideIcon,
} from "lucide-react";
import type { AttachmentMeta } from "@tw/types";

export const MAX_ATTACHMENT_FILES = 10;
export const MAX_ATTACHMENT_SIZE_BYTES = 30 * 1024 * 1024;

// dat/eml are deliberately excluded — they only ever arrive server-side
// via Graph's itemAttachment/TNEF handling, never through this picker.
// docm/xlsm/pptm (macro-enabled Office), msg, and executables are
// deliberately excluded too — must stay rejected, mirrors the backend
// allow-list in constants.py.
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
  "rtf",
  "odt",
  "ods",
  "ppt",
  "pptx",
  "odp",
  "bmp",
  "webp",
  "tiff",
  "tif",
  "ico",
  "heic",
  "heif",
  "svg",
  "mp4",
  "mov",
  "avi",
  "wmv",
  "mkv",
  "mp3",
  "wav",
  "m4a",
  "aac",
  "rar",
  "7z",
  "tar",
  "gz",
  "bz2",
  "py",
  "js",
  "ts",
  "java",
  "html",
  "css",
  "json",
  "xml",
  "sql",
  "md",
  "log",
];

// Never eligible for inline/preview rendering even though allow-listed
// above — SVG can carry embedded script, unsafe to render via a plain
// <img>/direct-navigation path. Mirrors the backend's
// NEVER_INLINE_EXTENSIONS in constants.py.
export const NEVER_INLINE_EXTENSIONS = ["svg"];

export const ATTACHMENT_ACCEPT_ATTR = ALLOWED_ATTACHMENT_EXTENSIONS.map((ext) => `.${ext}`).join(",");

const ICON_BY_EXTENSION: Record<string, LucideIcon> = {
  pdf: FileText,
  doc: FileText,
  docx: FileText,
  txt: FileText,
  rtf: FileText,
  odt: FileText,
  md: FileText,
  log: FileText,
  html: FileText,
  css: FileText,
  js: FileText,
  ts: FileText,
  py: FileText,
  java: FileText,
  json: FileText,
  xml: FileText,
  sql: FileText,
  xls: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  csv: FileSpreadsheet,
  ods: FileSpreadsheet,
  ppt: FileText,
  pptx: FileText,
  odp: FileText,
  png: Image,
  jpg: Image,
  jpeg: Image,
  gif: Image,
  bmp: Image,
  webp: Image,
  tiff: Image,
  tif: Image,
  ico: Image,
  heic: Image,
  heif: Image,
  svg: Image,
  mp4: Video,
  mov: Video,
  avi: Video,
  wmv: Video,
  mkv: Video,
  mp3: Music,
  wav: Music,
  m4a: Music,
  aac: Music,
  zip: Archive,
  rar: Archive,
  "7z": Archive,
  tar: Archive,
  gz: Archive,
  bz2: Archive,
};

function extensionOf(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

export function iconForFilename(filename: string): LucideIcon {
  return ICON_BY_EXTENSION[extensionOf(filename)] ?? FileIcon;
}

export function isImageAttachment(attachment: Pick<AttachmentMeta, "mime_type" | "filename">): boolean {
  const extension = extensionOf(attachment.filename);
  if (NEVER_INLINE_EXTENSIONS.includes(extension)) return false;
  if (attachment.mime_type) return attachment.mime_type.startsWith("image/");
  return ["png", "jpg", "jpeg", "gif"].includes(extension);
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

export function validateFiles(
  files: File[],
  maxFiles: number = MAX_ATTACHMENT_FILES
): FileValidationResult {
  const errors: string[] = [];
  const accepted: File[] = [];

  if (files.length > maxFiles) {
    errors.push(`Only ${maxFiles} files can be attached at once.`);
  }

  const withinLimit = files.slice(0, maxFiles);

  for (const file of withinLimit) {
    const extension = extensionOf(file.name);

    if (!ALLOWED_ATTACHMENT_EXTENSIONS.includes(extension)) {
      errors.push(`"${file.name}" has an unsupported file type.`);
      continue;
    }

    if (file.size > MAX_ATTACHMENT_SIZE_BYTES) {
      errors.push(
        `"${file.name}" exceeds the ${MAX_ATTACHMENT_SIZE_BYTES / (1024 * 1024)}MB size limit.`
      );
      continue;
    }

    accepted.push(file);
  }

  return { accepted, errors };
}
