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

import {
  DOMParser as ProseMirrorDOMParser,
  Fragment,
  type Node as ProseMirrorNode,
  type ResolvedPos,
  Slice,
} from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import DOMPurify from "dompurify";

import {
  EMAIL_DEFAULT_FONT_FAMILY,
  EMAIL_DEFAULT_FONT_SIZE,
  INDENT_STEP_PX,
  findFontFamilyOption,
  fontSizeToPoints,
} from "@tw/lib/emailHtml";

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
  "s",
  "strike",
  "del",
  "span",
  "ul",
  "ol",
  "li",
  "blockquote",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
  "img",
  "a",
];

const ALLOWED_ATTR = ["href", "src", "alt", "title", "colspan", "rowspan", "style"];

// ---------------------------------------------------------------
// Pasted inline-CSS normalization
// ---------------------------------------------------------------
//
// Office/web clipboard HTML carries dozens of inline declarations per
// run (mso-*, line-height, margins, explicit default fonts/colors).
// Only formatting the toolbar itself can represent survives, in the
// same shape the toolbar produces — so a paste never brings in huge
// fonts, odd margins, or properties the backend sanitizer would strip
// anyway. "Default-looking" values (black text, white background, the
// default 11pt size, left alignment) are dropped too: they'd only pin
// the pasted run to explicit formatting identical to the default.

const DEFAULT_TEXT_COLORS = new Set([
  "windowtext",
  "black",
  "#000",
  "#000000",
  "rgb(0,0,0)",
  "inherit",
  "initial",
  "currentcolor",
  "auto",
  "unset",
]);
const DEFAULT_BACKGROUNDS = new Set([
  "transparent",
  "white",
  "#fff",
  "#ffffff",
  "window",
  "none",
  "inherit",
  "initial",
  "unset",
  "rgba(0,0,0,0)",
  "rgb(255,255,255)",
]);
const SAFE_COLOR_VALUE = /^(#[0-9a-f]{3,8}|rgba?\([\d.\s,%]+\)|[a-z]{3,20})$/i;
const MIN_PASTED_FONT_PT = 7;
const MAX_PASTED_FONT_PT = 36;

function normalizeColor(value: string, defaults: Set<string>): string | null {
  const compact = value.trim().toLowerCase().replace(/\s+/g, "");
  if (!SAFE_COLOR_VALUE.test(compact) || defaults.has(compact)) return null;
  return compact;
}

// Lengths Word/Outlook emit for indentation (in, pt, cm) -> px.
function lengthToPx(value: string): number | null {
  const match = value.trim().match(/^(-?\d*\.?\d+)(px|pt|in|cm|mm|em)?$/i);
  if (!match) return null;
  const amount = Number(match[1]);
  const factor: Record<string, number> = { px: 1, pt: 4 / 3, in: 96, cm: 96 / 2.54, mm: 96 / 25.4, em: 16 };
  return amount * factor[(match[2] ?? "px").toLowerCase()];
}

export function filterPastedStyle(style: string, tagName: string): string | null {
  const kept: string[] = [];
  const isBlock = /^(p|div|li|blockquote)$/i.test(tagName);

  for (const declaration of style.split(";")) {
    const index = declaration.indexOf(":");
    if (index === -1) continue;
    const name = declaration.slice(0, index).trim().toLowerCase();
    const value = declaration.slice(index + 1).replace(/!important/i, "").trim();
    if (!value || /url\(|expression|javascript:|[<>\\]/i.test(value)) continue;

    switch (name) {
      case "color": {
        const color = normalizeColor(value, DEFAULT_TEXT_COLORS);
        if (color) kept.push(`color: ${color}`);
        break;
      }
      case "background":
      case "background-color": {
        const color = normalizeColor(value, DEFAULT_BACKGROUNDS);
        if (color) kept.push(`background-color: ${color}`);
        break;
      }
      case "font-family": {
        const option = findFontFamilyOption(value);
        if (option && option.value !== EMAIL_DEFAULT_FONT_FAMILY) kept.push(`font-family: ${option.value}`);
        break;
      }
      case "font-size": {
        const points = fontSizeToPoints(value);
        const numeric = points ? Number(points) : NaN;
        if (
          points &&
          numeric >= MIN_PASTED_FONT_PT &&
          numeric <= MAX_PASTED_FONT_PT &&
          `${points}pt` !== EMAIL_DEFAULT_FONT_SIZE
        ) {
          kept.push(`font-size: ${points}pt`);
        }
        break;
      }
      case "font-weight":
        if (/^(bold|bolder|[6-9]00)$/i.test(value)) kept.push("font-weight: bold");
        break;
      case "font-style":
        if (/^italic$/i.test(value)) kept.push("font-style: italic");
        break;
      case "text-decoration":
      case "text-decoration-line":
        if (/underline|line-through/i.test(value)) {
          kept.push(`text-decoration: ${value.toLowerCase().match(/underline|line-through/g)!.join(" ")}`);
        }
        break;
      case "text-align":
        if (isBlock && /^(center|right|justify)$/i.test(value)) kept.push(`text-align: ${value.toLowerCase()}`);
        break;
      case "margin-left": {
        const px = lengthToPx(value);
        if (isBlock && px && px >= INDENT_STEP_PX / 2) kept.push(`margin-left: ${Math.round(px)}px`);
        break;
      }
      default:
        break;
    }
  }

  return kept.length > 0 ? kept.join("; ") : null;
}

// ---------------------------------------------------------------
// Office (Outlook/Word) clipboard HTML normalization
// ---------------------------------------------------------------

const ZERO_LENGTH = /^-?0*\.?0+(in|pt|px|cm|mm|em)?$/i;
const OFFICE_HTML_SIGNATURE = /urn:schemas-microsoft-com|class=["']?Mso|mso-/i;

function isEmptyBlock(element: Element): boolean {
  if (element.querySelector("img, table")) return false;
  return (element.textContent ?? "").replace(/ /g, " ").trim().length === 0;
}

function styleDeclaration(style: string | null, property: string): string | null {
  if (!style) return null;
  const match = style.match(new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`, "i"));
  return match ? match[1].trim() : null;
}

function marginBottomOf(style: string | null): string | null {
  const longhand = styleDeclaration(style, "margin-bottom");
  if (longhand) return longhand;
  const shorthand = styleDeclaration(style, "margin");
  if (!shorthand) return null;
  const parts = shorthand.split(/\s+/);
  return parts.length >= 3 ? parts[2] : parts[0];
}

// Outlook writes every Enter as its own zero-margin <p class=MsoNormal>
// and a blank line as an empty one (Word's own Normal style instead has
// ~8pt "space after", making each <p> a real paragraph). Reads the
// clipboard's own <style> block to tell the two apart.
function msoNormalHasZeroGap(doc: Document): boolean {
  const css = Array.from(doc.querySelectorAll("style"))
    .map((style) => style.textContent ?? "")
    .join("\n");
  const rule = css.match(/p\.MsoNormal[^{]*\{([^}]*)\}/i);
  if (!rule) return false;
  const gap = marginBottomOf(rule[1].replace(/\s+/g, " "));
  return gap !== null && ZERO_LENGTH.test(gap);
}

// Zero-gap Office paragraphs are LINES, not paragraphs, in this
// editor's model: a run of consecutive non-empty ones becomes one <p>
// joined by <br> (Shift+Enter), and the empty spacer paragraphs between
// runs become plain paragraph boundaries — so a pasted Outlook email
// keeps its exact line/paragraph structure instead of gaining a
// paragraph gap after every line.
function mergeOfficeLineParagraphs(doc: Document, classGapIsZero: boolean) {
  const paragraphs = Array.from(doc.body.querySelectorAll("p")).filter(
    (p) => !/mso-list/i.test(p.getAttribute("style") ?? "") && !p.closest("li, td, th")
  );
  const isLine = (p: Element) => {
    const inlineGap = marginBottomOf(p.getAttribute("style"));
    if (inlineGap !== null) return ZERO_LENGTH.test(inlineGap);
    return classGapIsZero && /MsoNormal/i.test(p.className);
  };

  let runHead: Element | null = null;
  for (const paragraph of paragraphs) {
    if (!isLine(paragraph)) {
      runHead = null;
      continue;
    }
    if (isEmptyBlock(paragraph)) {
      paragraph.remove();
      runHead = null;
      continue;
    }
    // Only merge true siblings (whitespace-only text between them) —
    // a paragraph in another container/section starts a new run.
    let previous = paragraph.previousSibling;
    while (previous && previous.nodeType === 3 && !(previous.textContent ?? "").trim()) {
      previous = previous.previousSibling;
    }
    if (runHead && previous === runHead) {
      runHead.appendChild(doc.createElement("br"));
      while (paragraph.firstChild) runHead.appendChild(paragraph.firstChild);
      paragraph.remove();
    } else {
      runHead = paragraph;
    }
  }
}

const WORD_BULLET_GLYPH = /^[·•o§▪■◦•·-]$/;

// Word/Outlook don't put real <ul>/<ol> on the clipboard — each item is
// a <p style="mso-list:l0 level2 lfo1"> whose bullet/number is literal
// text inside a `mso-list:Ignore` span. Rebuild real (nested) lists so
// the editor gets proper list items instead of glyph-prefixed text.
function convertWordLists(doc: Document) {
  const listParagraphs = Array.from(doc.body.querySelectorAll("p")).filter((p) =>
    /mso-list:\s*l\d+\s+level\d+/i.test(p.getAttribute("style") ?? "")
  );
  if (listParagraphs.length === 0) return;

  let stack: { level: number; list: HTMLElement }[] = [];
  let lastParagraph: ChildNode | null = null;

  for (const paragraph of listParagraphs) {
    const level = Number((paragraph.getAttribute("style") ?? "").match(/level(\d+)/i)?.[1] ?? 1);

    let marker = "";
    paragraph.querySelectorAll("span").forEach((span) => {
      if (/mso-list:\s*ignore/i.test(span.getAttribute("style") ?? "")) {
        marker = marker || (span.textContent ?? "").replace(/ /g, " ").trim();
        span.remove();
      }
    });
    const ordered = marker !== "" && !WORD_BULLET_GLYPH.test(marker) && /^\(?[0-9a-z]{1,5}[.)]$/i.test(marker);

    // A new group starts unless this item directly follows the
    // previous list paragraph (whitespace-only text in between).
    let previous = paragraph.previousSibling;
    while (previous && previous.nodeType === 3 && !(previous.textContent ?? "").trim()) {
      previous = previous.previousSibling;
    }
    const continues = lastParagraph !== null && previous === lastParagraph;
    if (!continues) stack = [];

    while (stack.length > 0 && stack[stack.length - 1].level > level) stack.pop();
    let top = stack[stack.length - 1];
    if (!top || top.level < level) {
      const list = doc.createElement(ordered ? "ol" : "ul");
      if (top) {
        const parentItem = top.list.lastElementChild ?? top.list.appendChild(doc.createElement("li"));
        parentItem.appendChild(list);
      } else {
        paragraph.before(list);
      }
      top = { level, list };
      stack.push(top);
    }

    const item = doc.createElement("li");
    const content = doc.createElement("p");
    while (paragraph.firstChild) content.appendChild(paragraph.firstChild);
    item.appendChild(content);
    top.list.appendChild(item);

    // Keep a placeholder at the paragraph's spot so the sibling check
    // above still recognizes the next item as part of this same list.
    const placeholder = doc.createComment("list-item");
    paragraph.replaceWith(placeholder);
    lastParagraph = placeholder;
  }
}

// Legacy <font color face size> (old Outlook/Word, some web mail) ->
// a <span style> the TextStyle mark understands.
const FONT_TAG_SIZES: Record<string, string> = { "1": "8pt", "2": "10pt", "3": "12pt", "4": "14pt", "5": "18pt", "6": "24pt", "7": "36pt" };

function convertFontTags(doc: Document) {
  doc.body.querySelectorAll("font").forEach((font) => {
    const span = doc.createElement("span");
    const declarations: string[] = [];
    const color = font.getAttribute("color");
    const face = font.getAttribute("face");
    const size = font.getAttribute("size");
    if (color) declarations.push(`color: ${color}`);
    if (face) declarations.push(`font-family: ${face}`);
    if (size && FONT_TAG_SIZES[size]) declarations.push(`font-size: ${FONT_TAG_SIZES[size]}`);
    if (declarations.length > 0) span.setAttribute("style", declarations.join("; "));
    while (font.firstChild) span.appendChild(font.firstChild);
    font.replaceWith(span);
  });
}

/**
 * Structural clean-up applied to raw clipboard HTML before DOMPurify:
 * Word list paragraphs -> real lists, Outlook line paragraphs -> <br>,
 * <font> -> <span style>, and empty spacer blocks (an Office/web blank
 * line — this editor's paragraphs already carry their own gap) removed.
 * Runs in an inert document, so nothing is fetched or executed.
 */
export function normalizePastedHtmlStructure(rawHtml: string): string {
  if (typeof DOMParser === "undefined") return rawHtml;
  const doc = new DOMParser().parseFromString(rawHtml, "text/html");

  if (OFFICE_HTML_SIGNATURE.test(rawHtml)) {
    convertWordLists(doc);
    mergeOfficeLineParagraphs(doc, msoNormalHasZeroGap(doc));
  }
  convertFontTags(doc);

  doc.body.querySelectorAll("p, div").forEach((block) => {
    if (isEmptyBlock(block) && !block.querySelector("p, div, li")) block.remove();
  });

  return doc.body.innerHTML;
}

// DOMPurify's own built-in URI sanitization already strips
// javascript:/data: (etc.) from href/src regardless of ALLOWED_ATTR —
// this allow-list only controls which *tags*/*attributes* survive at
// all, not which URL schemes are safe on the ones that do (that's a
// separate, always-on protection DOMPurify applies to any attribute
// it recognizes as URL-bearing). `style` is the one attribute whose
// VALUE is rewritten here too (filterPastedStyle) — via a hook that is
// registered only for the duration of this call, so no other DOMPurify
// use is affected.
export function sanitizePastedHtml(rawHtml: string): string {
  if (typeof window === "undefined") return "";

  DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
    if (data.attrName !== "style") return;
    const filtered = filterPastedStyle(data.attrValue, node.nodeName);
    if (filtered) {
      data.attrValue = filtered;
    } else {
      data.keepAttr = false;
    }
  });
  try {
    return DOMPurify.sanitize(normalizePastedHtmlStructure(rawHtml), {
      ALLOWED_TAGS,
      ALLOWED_ATTR,
      ALLOW_DATA_ATTR: false,
    });
  } finally {
    DOMPurify.removeHook("uponSanitizeAttribute");
  }
}

/**
 * ProseMirror `clipboardTextParser` for plain-text paste (and Ctrl+
 * Shift+V). ProseMirror's own default makes EVERY newline a separate
 * paragraph — a hard-wrapped plain-text email pasted in became one
 * paragraph per visual line, each with its own paragraph gap, and real
 * blank-line paragraph breaks were lost. Here a blank line separates
 * paragraphs and a single newline is a line break (Shift+Enter).
 */
export function parsePlainTextClipboard(text: string, $context: ResolvedPos, _plain: boolean, view: EditorView): Slice {
  const { schema } = view.state;
  const normalized = text.replace(/\r\n?/g, "\n").replace(/^\n+|\n+$/g, "");
  if (!normalized) return Slice.empty;

  const marks = $context.marks();
  const paragraphs = normalized.split(/\n[ \t]*\n\s*/).map((block) => {
    const content: ProseMirrorNode[] = [];
    block.split("\n").forEach((line, index) => {
      if (index > 0 && schema.nodes.hardBreak) content.push(schema.nodes.hardBreak.create());
      if (line) content.push(schema.text(line, marks));
    });
    return schema.nodes.paragraph.create(null, content);
  });
  return new Slice(Fragment.from(paragraphs), 1, 1);
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
  // Default (collapsing) whitespace handling — clipboard HTML's own
  // source formatting (newlines/indentation between and inside tags)
  // is not content. `preserveWhitespace: true` kept it, turning the
  // whitespace between pasted blocks into stray near-empty paragraphs
  // (unexpected blank lines). Real spacing Office encodes as &nbsp;
  // survives either way.
  const slice = parser.parseSlice(container);
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
