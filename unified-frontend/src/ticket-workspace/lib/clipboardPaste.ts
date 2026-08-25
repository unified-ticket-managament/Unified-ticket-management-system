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

// Office apps (Excel, in particular) place multiple clipboard formats
// simultaneously when copying a cell range: a real `text/html` `<table>`
// (CF_HTML) *and* a flattened bitmap rendering of the same selection, so
// image-only apps can still paste something. `createPasteHandler` below
// therefore checks whether the HTML is "meaningful" (a real `<table>`,
// or real text once any `<img>` is discounted) before ever letting an
// image file win — a genuine screenshot (Snipping Tool, Win+Shift+S) has
// neither `text/html` at all nor meaningful HTML when it does, so it
// still always resolves to an image paste.
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

// The discriminator `createPasteHandler` uses to decide whether pasted
// HTML deserves to win over an image file present in the same clipboard
// event: does it carry something a flat bitmap can't represent — a real
// `<table>`, or text once every `<img>` is discounted? A genuine
// screenshot has neither, so this can never misroute one away from
// becoming an image. Operates on already-*sanitized* HTML so a payload
// of only `<style>`/unknown tags never counts as meaningful.
export function isMeaningfulPastedHtml(sanitizedHtml: string): boolean {
  if (typeof document === "undefined" || !sanitizedHtml.trim()) return false;

  // An inert document — never appended to the live DOM — so assigning
  // `innerHTML` here can't trigger a real network fetch for an `<img
  // src>` just to inspect the markup's shape.
  const inert = document.implementation.createHTMLDocument("");
  const container = inert.createElement("div");
  container.innerHTML = sanitizedHtml;

  if (container.querySelector("table")) return true;

  container.querySelectorAll("img").forEach((img) => img.remove());
  return (container.textContent ?? "").replace(/ /g, " ").trim().length > 0;
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

// Parses an already-mutated container into a ProseMirror slice and, if
// it's non-empty, dispatches it as the one atomic replace-selection
// transaction for this paste. Returns false (no dispatch) for a slice
// that collapsed to nothing — e.g. a lone base64 `<img>` that
// `PastedImage`'s `allowBase64:false` rejects — so the caller can fall
// through to another branch instead of silently eating the paste.
function insertParsedContainer(view: EditorView, container: HTMLElement): boolean {
  const parser = ProseMirrorDOMParser.fromSchema(view.state.schema);
  const slice = parser.parseSlice(container, { preserveWhitespace: true });
  if (slice.content.size === 0) return false;

  // replaceSelection, never an end-of-document insert — pasting mid-
  // message (with a signature or other content already below the
  // cursor) must never get appended past it.
  view.dispatch(view.state.tr.replaceSelection(slice));
  return true;
}

function tryInsertSanitizedHtml(view: EditorView, sanitizedHtml: string): boolean {
  if (!sanitizedHtml.trim()) return false;
  const container = document.createElement("div");
  container.innerHTML = sanitizedHtml;
  return insertParsedContainer(view, container);
}

// Handles the mixed text+image case: sanitized HTML that carries one or
// more `<img>` tags *and* the same clipboard event also carried real
// image `File`s (e.g. a Word paragraph with one inline image). None of
// the `<img>` elements' own `src` values are usable as-is — a pasted
// `<img src>` is never a real `cid:`/already-uploaded reference, even an
// `http(s)` one would be dropped by the backend's cid-only outbound
// filter at send time, and Word's own inline images use inaccessible
// `file://` references — so every `<img>` here is a placeholder to be
// resolved against the clipboard's real files, matched positionally in
// document/clipboard order (the common case — one inline image — is
// exactly a 1:1 match). Rewriting each matched `<img>` in place (not
// replacing the element) preserves its exact position in the flowing
// text; the whole result is dispatched as one atomic transaction so text
// and images land together, in order.
function interleaveAndInsert(
  view: EditorView,
  sanitizedHtml: string,
  imageFiles: File[],
  callbacks: ImagePasteCallbacks
): boolean {
  const container = document.createElement("div");
  container.innerHTML = sanitizedHtml;

  const imgEls = Array.from(container.querySelectorAll("img"));

  // No `<img>` tag in the HTML at all — any accompanying image file(s)
  // are a flattened-bitmap companion format (Excel/Office's own
  // rendering of the whole copied selection, sent alongside the real
  // HTML so image-only apps can still paste something — see
  // `getClipboardImageFiles`), not a distinct inline picture to
  // preserve. Insert the HTML as-is and leave the redundant bitmap(s)
  // untouched/unreferenced — appending them as trailing images would
  // silently reintroduce the exact "becomes an image" bug this whole
  // branch exists to fix, just with an extra picture bolted on.
  if (imgEls.length === 0) {
    return insertParsedContainer(view, container);
  }

  const matchCount = Math.min(imgEls.length, imageFiles.length);
  const matchedPairs: { file: File; localId: string }[] = [];

  for (let i = 0; i < matchCount; i++) {
    const file = imageFiles[i];
    const localId = generateLocalId();
    const objectUrl = URL.createObjectURL(file);
    imgEls[i].setAttribute("src", objectUrl);
    imgEls[i].setAttribute("data-local-id", localId);
    imgEls[i].setAttribute("data-upload-status", "uploading");
    matchedPairs.push({ file, localId });
  }

  // More <img> tags than files: the leftover tags have no file to
  // resolve against (e.g. a data: URI DOMPurify already stripped, or an
  // otherwise-broken reference) — drop them, same as today's behavior
  // for an unresolvable image reference, rather than send a dead src.
  for (let i = matchCount; i < imgEls.length; i++) {
    imgEls[i].remove();
  }

  const inserted = insertParsedContainer(view, container);
  if (!inserted) return false;

  for (const { file, localId } of matchedPairs) {
    callbacks.onImageFile(file, localId);
  }

  // More files than <img> tags: every pasted image must still end up
  // uploaded somewhere, just not perfectly interleaved — append the
  // leftovers as trailing placeholders immediately after, in clipboard
  // order, via the same path a plain image-only paste already uses.
  for (let i = matchCount; i < imageFiles.length; i++) {
    const file = imageFiles[i];
    const localId = generateLocalId();
    insertImagePlaceholder(view, file, localId);
    callbacks.onImageFile(file, localId);
  }

  return true;
}

/**
 * Returns a ProseMirror-shaped `handlePaste` handler for `editorProps`.
 *
 * Branch order:
 * 1. HTML carrying something a flat bitmap can't represent (a real
 *    `<table>`, or real text once `<img>`s are discounted) — see
 *    `isMeaningfulPastedHtml`. Wins even when the clipboard also carries
 *    an image file (Excel/Office's flattened-bitmap companion format).
 * 2. A real image paste (screenshot, copied image file, or HTML from
 *    step 1 that turned out not to be meaningful/insertable).
 * 3. HTML that exists but was never "meaningful" (e.g. a browser "Copy
 *    image" whose `text/html` is just a bare `<img>` tag) — inserted
 *    as-is rather than dropped.
 * 4. Plain `text/plain` paste — returning `false` leaves it entirely to
 *    ProseMirror's own untouched default behavior.
 */
export function createPasteHandler(callbacks: ImagePasteCallbacks) {
  return function handlePaste(view: EditorView, event: ClipboardEvent): boolean {
    const clipboardData = event.clipboardData;
    if (!clipboardData) return false;

    const rawHtml = getPastedHtml(clipboardData);
    const sanitized = rawHtml ? sanitizePastedHtml(rawHtml) : null;
    const imageFiles = getClipboardImageFiles(clipboardData);

    if (sanitized && isMeaningfulPastedHtml(sanitized)) {
      event.preventDefault();
      const inserted =
        imageFiles.length > 0
          ? interleaveAndInsert(view, sanitized, imageFiles, callbacks)
          : tryInsertSanitizedHtml(view, sanitized);
      if (inserted) return true;
    }

    if (imageFiles.length > 0) {
      event.preventDefault();
      for (const file of imageFiles) {
        const localId = generateLocalId();
        insertImagePlaceholder(view, file, localId);
        callbacks.onImageFile(file, localId);
      }
      return true;
    }

    if (sanitized && tryInsertSanitizedHtml(view, sanitized)) {
      event.preventDefault();
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
