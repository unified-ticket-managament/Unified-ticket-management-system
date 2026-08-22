// clipboardPaste.ts
//
// The single shared implementation of Outlook-style clipboard paste
// (plain text / rich HTML / HTML tables / pasted screenshots) for
// every rich-text composer in this app (Mail Compose/Reply/Reply All
// via RichTextEditor.tsx, and — once converted — the Ticket
// Workspace Reply/Internal Note composer, which reuses RichTextEditor
// too). There is exactly one `editorProps.handlePaste`/`handleDrop`
// wiring in the whole app (RichTextEditor.tsx) — this module is only
// ever called from there, so paste behavior is never duplicated.
//
// Detection uses the plain browser ClipboardEvent/DataTransfer API —
// no navigator.clipboard.read() permission prompt is needed or used.

import { DOMParser as ProseMirrorDOMParser } from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import DOMPurify from "dompurify";

// ---------------------------------------------------------------
// Detection — pure, framework-agnostic
// ---------------------------------------------------------------

export function getPastedHtml(clipboardData: DataTransfer): string | null {
  const html = clipboardData.getData("text/html");
  return html && html.trim().length > 0 ? html : null;
}

export function hasHtml(clipboardData: DataTransfer): boolean {
  return getPastedHtml(clipboardData) !== null;
}

// Images first, always — a Windows Snipping Tool copy (and most
// screenshot tools) puts the bitmap in `files`/`items` with NO
// `text/html` entry at all. Checking HTML before images would either
// insert nothing, or in some browsers fall through to a bare
// `text/plain` filename/blob reference — exactly the "must not appear
// as a bare filename or broken image" failure this feature exists to
// avoid.
export function getClipboardImageFiles(clipboardData: DataTransfer): File[] {
  const files: File[] = [];

  if (clipboardData.files && clipboardData.files.length > 0) {
    for (const file of Array.from(clipboardData.files)) {
      if (file.type.startsWith("image/")) files.push(file);
    }
  }

  // Some browsers only expose a pasted screenshot via `items`
  // (kind === "file"), not `files` — check both, preferring `files`
  // when it already found something so we never double-collect the
  // same image from two clipboard representations of one paste.
  if (files.length === 0 && clipboardData.items) {
    for (const item of Array.from(clipboardData.items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
  }

  return files;
}

// ---------------------------------------------------------------
// Sanitization
// ---------------------------------------------------------------

const ALLOWED_TAGS = [
  "p",
  "div",
  "br",
  "strong",
  "b",
  "em",
  "i",
  "u",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
  "img",
  "a",
];

const ALLOWED_ATTR = ["href", "src", "alt", "title", "colspan", "rowspan"];

// DOMPurify's own built-in URI sanitization already strips
// javascript:/data: (etc.) from href/src regardless of ALLOWED_ATTR —
// this allow-list only controls which *tags*/*attributes* survive at
// all, not which URL schemes are safe on the ones that do (that's a
// separate, always-on protection DOMPurify applies to any attribute
// it recognizes as URL-bearing).
export function sanitizePastedHtml(rawHtml: string): string {
  if (typeof window === "undefined") return "";

  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
  });
}

// ---------------------------------------------------------------
// TipTap/ProseMirror integration — factories consumed only from
// RichTextEditor.tsx's editorProps.handlePaste/handleDrop.
// ---------------------------------------------------------------

function generateLocalId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface ImagePasteCallbacks {
  /**
   * Called once per pasted/dropped image file, immediately after its
   * local-preview node has already been inserted into the document
   * at `localId`. Fire-and-forget from this module's point of view —
   * the caller (RichTextEditor.tsx's upload-reconciliation hook) owns
   * uploading the file and patching the node's attributes once the
   * upload resolves.
   */
  onImageFile: (file: File, localId: string) => void;
}

function insertImagePlaceholder(view: EditorView, file: File, localId: string): void {
  const imageType = view.state.schema.nodes.image;
  if (!imageType) return;

  const objectUrl = URL.createObjectURL(file);
  const node = imageType.create({
    src: objectUrl,
    "data-local-id": localId,
    "data-upload-status": "uploading",
  });

  // replaceSelectionWith moves the selection to just after the
  // inserted node, so pasting/dropping several images in one event
  // — processed in a synchronous loop — naturally preserves clipboard
  // order with no extra bookkeeping.
  view.dispatch(view.state.tr.replaceSelectionWith(node));
}

function insertSanitizedHtml(view: EditorView, rawHtml: string): void {
  const sanitized = sanitizePastedHtml(rawHtml);
  if (!sanitized.trim()) return;

  const container = document.createElement("div");
  container.innerHTML = sanitized;

  const parser = ProseMirrorDOMParser.fromSchema(view.state.schema);
  const slice = parser.parseSlice(container, { preserveWhitespace: true });

  // replaceSelection, never an end-of-document insert — pasting mid-
  // message (with a signature or other content already below the
  // cursor) must never get appended past it.
  view.dispatch(view.state.tr.replaceSelection(slice));
}

/**
 * Returns a ProseMirror-shaped `handlePaste` handler for
 * `editorProps`. Branch order: images, then HTML, then — by
 * returning `false` — plain text is left entirely to ProseMirror's
 * own untouched default paste behavior (the lowest-risk way to
 * guarantee zero regression for ordinary text paste).
 */
export function createPasteHandler(callbacks: ImagePasteCallbacks) {
  return function handlePaste(view: EditorView, event: ClipboardEvent): boolean {
    const clipboardData = event.clipboardData;
    if (!clipboardData) return false;

    const imageFiles = getClipboardImageFiles(clipboardData);
    if (imageFiles.length > 0) {
      event.preventDefault();
      for (const file of imageFiles) {
        const localId = generateLocalId();
        insertImagePlaceholder(view, file, localId);
        callbacks.onImageFile(file, localId);
      }
      return true;
    }

    const html = getPastedHtml(clipboardData);
    if (html) {
      event.preventDefault();
      insertSanitizedHtml(view, html);
      return true;
    }

    return false;
  };
}

/**
 * Returns a ProseMirror-shaped `handleDrop` handler for
 * `editorProps` — covers dragging a screenshot/image file in from
 * the file system (a common companion workflow to Ctrl+V). HTML/text
 * drag-drop is deliberately left to ProseMirror's own default (this
 * feature's scope is paste, not drag-and-drop composition).
 */
export function createDropHandler(callbacks: ImagePasteCallbacks) {
  return function handleDrop(view: EditorView, event: DragEvent): boolean {
    const files = event.dataTransfer?.files;
    if (!files || files.length === 0) return false;

    const imageFiles = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length === 0) return false;

    event.preventDefault();

    const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
    if (coords) {
      const selection = TextSelection.near(view.state.doc.resolve(coords.pos));
      view.dispatch(view.state.tr.setSelection(selection));
    }

    for (const file of imageFiles) {
      const localId = generateLocalId();
      insertImagePlaceholder(view, file, localId);
      callbacks.onImageFile(file, localId);
    }

    return true;
  };
}
