import { MAX_ATTACHMENT_FILES, validateFiles, type FileValidationResult } from "@tw/lib/attachmentMeta";

// Shared "intake" helpers for every way a file can reach an attachment
// list — the Browse button, drag-and-drop, and clipboard paste. Nothing
// here has its own allow-list or limits: validation always goes through
// attachmentMeta's validateFiles, so all three input methods reject
// exactly the same files.

export function attachmentDedupeKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

// The dedupe-then-validate step that FileDropzone and AttachmentUploader
// each used to inline: already-attached files win, new files that match
// an existing one on name/size/lastModified are dropped silently.
export function mergeAttachmentFiles(
  existing: File[],
  incoming: FileList | File[],
  maxFiles: number = MAX_ATTACHMENT_FILES
): FileValidationResult {
  const existingKeys = new Set(existing.map(attachmentDedupeKey));
  const newFiles = Array.from(incoming).filter((file) => !existingKeys.has(attachmentDedupeKey(file)));
  return validateFiles([...existing, ...newFiles], maxFiles);
}

// True only for a drag that carries real files — a text selection or
// link being dragged around must never be treated as an attachment.
export function isFileDrag(dataTransfer: DataTransfer | null | undefined): boolean {
  if (!dataTransfer?.types) return false;
  return Array.from(dataTransfer.types).includes("Files");
}

// During dragenter/dragover browsers hide file contents but still
// expose each item's MIME type — enough to tell "images only" apart.
export function isImageOnlyDrag(dataTransfer: DataTransfer | null | undefined): boolean {
  const items = dataTransfer?.items;
  if (!items || items.length === 0) return false;
  return Array.from(items).every((item) => item.kind === "file" && item.type.startsWith("image/"));
}

// Some browsers hand back an unnamed blob for a pasted screenshot, which
// validateFiles would reject for having no extension.
function withFileName(file: File): File {
  if (file.name) return file;
  const extension = file.type.split("/")[1]?.replace("jpeg", "jpg") || "bin";
  return new File([file], `pasted-file.${extension}`, { type: file.type, lastModified: file.lastModified });
}

// Every real file on the clipboard. `files` is preferred, `items` is the
// fallback (some browsers expose a pasted screenshot only there) —
// never both, so one paste can't be collected twice.
export function getClipboardFiles(clipboardData: DataTransfer | null | undefined): File[] {
  if (!clipboardData) return [];

  const files = clipboardData.files ? Array.from(clipboardData.files) : [];
  if (files.length > 0) return files.map(withFileName);

  const fromItems: File[] = [];
  if (clipboardData.items) {
    for (const item of Array.from(clipboardData.items)) {
      if (item.kind !== "file") continue;
      const file = item.getAsFile();
      if (file) fromItems.push(withFileName(file));
    }
  }
  return fromItems;
}

export interface PasteClassification {
  // Files that should become normal attachments.
  attach: File[];
  // True when the paste is fully consumed by the attachment flow, so the
  // caller must stop the editor/input from also pasting something.
  consumed: boolean;
}

// Decides what a paste means for an attachment-enabled composer.
//  - Inside the rich-text editor, images stay with TipTap (inline-image
//    flow, untouched); only non-image files become attachments.
//  - Anywhere else in the composer, images are attachments too — unless
//    the clipboard also carries plain text, which marks an Office-style
//    "text + flattened bitmap" copy that is really a text paste.
//  - A clipboard with no files at all is never touched.
export function classifyPaste(clipboardData: DataTransfer | null | undefined, inEditor: boolean): PasteClassification {
  const files = getClipboardFiles(clipboardData);
  if (files.length === 0) return { attach: [], consumed: false };

  const images = files.filter(isImageFile);
  const others = files.filter((file) => !isImageFile(file));
  const hasPlainText = (clipboardData?.getData("text/plain") ?? "").trim().length > 0;

  if (inEditor) {
    return { attach: others, consumed: others.length > 0 && images.length === 0 };
  }

  const attachImages = images.length > 0 && !hasPlainText;
  const attach = attachImages ? [...others, ...images] : others;
  return { attach, consumed: attach.length > 0 && (attachImages || images.length === 0) };
}

export interface DropClassification {
  attach: File[];
  // True when the browser/editor must not see this drop at all.
  consumed: boolean;
}

// Drop counterpart of classifyPaste: inside the editor images go to
// TipTap's own drop handler and everything else to attachments; outside
// the editor every file is an attachment.
export function classifyDrop(dataTransfer: DataTransfer | null | undefined, inEditor: boolean): DropClassification {
  if (!isFileDrag(dataTransfer)) return { attach: [], consumed: false };

  const files = dataTransfer?.files ? Array.from(dataTransfer.files) : [];
  if (files.length === 0) return { attach: [], consumed: false };

  if (!inEditor) return { attach: files, consumed: true };

  const images = files.filter(isImageFile);
  const others = files.filter((file) => !isImageFile(file));
  return { attach: others, consumed: images.length === 0 };
}
