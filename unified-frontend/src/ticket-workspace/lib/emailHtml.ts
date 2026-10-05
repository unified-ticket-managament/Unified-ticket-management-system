// emailHtml.ts
//
// The single source of truth for how a composed message LOOKS — shared
// by the editor (RichTextEditor.tsx + the `.utms-email-editor` rules in
// app/globals.css, which must mirror the EMAIL_* values below) and by
// the HTML that is actually sent (toEmailHtml, applied at every
// send/draft-save via richText.ts's buildOutgoingBodyHtml).
//
// Why send-time inlining is needed at all: TipTap's getHTML() emits
// bare semantic markup (`<p>`, `<ul>`) and the editor's look comes from
// stylesheet rules that never leave the browser. Email clients apply
// their OWN defaults to bare markup — Outlook desktop maps a bare <p>
// to its "Normal (Web)" style (~14pt of space above AND below every
// paragraph) and renders an unstyled body in Times New Roman — so the
// recipient saw large, doubled paragraph gaps the author never saw.
// Every value the editor's stylesheet sets is therefore written onto
// the elements themselves as inline `style`, the only styling every
// mainstream email client honors (backend html_sanitizer.py's outbound
// CSS allow-list accepts exactly these properties).

export const EMAIL_DEFAULT_FONT_FAMILY = "'Times New Roman', Times, serif";
export const EMAIL_DEFAULT_FONT_SIZE = "11pt";
export const EMAIL_LINE_HEIGHT = "1.35";
export const EMAIL_TEXT_COLOR = "#000000";
export const EMAIL_PARAGRAPH_GAP = "10px";
export const EMAIL_LINK_COLOR = "#0563c1";
export const EMAIL_BLOCKQUOTE_BORDER = "2px solid #cccccc";
export const EMAIL_BLOCKQUOTE_COLOR = "#555555";
export const EMAIL_BLOCKQUOTE_PADDING = "12px";
export const INDENT_STEP_PX = 40;
export const MAX_INDENT_LEVEL = 8;

const BULLET_STYLES = ["disc", "circle", "square"];
const NUMBER_STYLES = ["decimal", "lower-alpha", "lower-roman"];

export function listStyleForDepth(listTag: "ul" | "ol", depth: number): string {
  const styles = listTag === "ul" ? BULLET_STYLES : NUMBER_STYLES;
  return styles[depth % styles.length];
}

// ---------------------------------------------------------------
// Toolbar option lists
// ---------------------------------------------------------------

export interface FontFamilyOption {
  label: string;
  value: string;
}

// Email-safe stacks — each falls back to a metrically similar font a
// recipient without the first choice is likely to have.
export const FONT_FAMILY_OPTIONS: FontFamilyOption[] = [
  { label: "Times New Roman", value: EMAIL_DEFAULT_FONT_FAMILY },
  { label: "Arial", value: "Arial, Helvetica, sans-serif" },
  { label: "Calibri", value: "Calibri, Carlito, Arial, sans-serif" },
  { label: "Cambria", value: "Cambria, Georgia, serif" },
  { label: "Courier New", value: "'Courier New', Courier, monospace" },
  { label: "Georgia", value: "Georgia, serif" },
  { label: "Segoe UI", value: "'Segoe UI', Tahoma, Arial, sans-serif" },
  { label: "Tahoma", value: "Tahoma, Geneva, sans-serif" },
  { label: "Trebuchet MS", value: "'Trebuchet MS', Helvetica, sans-serif" },
  { label: "Verdana", value: "Verdana, Geneva, sans-serif" },
];

// Points, like Outlook/Word — the unit their own size picker uses.
export const FONT_SIZE_OPTIONS = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32"];

export const TEXT_COLOR_PALETTE: { label: string; value: string }[] = [
  { label: "Black", value: "#000000" },
  { label: "Dark gray", value: "#595959" },
  { label: "Gray", value: "#7f7f7f" },
  { label: "Dark red", value: "#c00000" },
  { label: "Red", value: "#ff0000" },
  { label: "Orange", value: "#ed7d31" },
  { label: "Gold", value: "#ffc000" },
  { label: "Green", value: "#00b050" },
  { label: "Dark green", value: "#375623" },
  { label: "Light blue", value: "#00b0f0" },
  { label: "Blue", value: "#0070c0" },
  { label: "Dark blue", value: "#002060" },
  { label: "Purple", value: "#7030a0" },
  { label: "Pink", value: "#e83e8c" },
];

export const HIGHLIGHT_PALETTE: { label: string; value: string }[] = [
  { label: "Yellow", value: "#ffff00" },
  { label: "Bright green", value: "#00ff00" },
  { label: "Turquoise", value: "#00ffff" },
  { label: "Pink", value: "#ff00ff" },
  { label: "Light orange", value: "#fbd5b5" },
  { label: "Light blue", value: "#bdd7ee" },
  { label: "Light green", value: "#c6efce" },
  { label: "Light gray", value: "#d9d9d9" },
];

// First family name only, unquoted/lowercased — "Arial, sans-serif"
// and "'arial'" both identify the Arial option.
export function fontFamilyKey(value: string | null | undefined): string {
  if (!value) return "";
  return value.split(",")[0].trim().replace(/^['"]|['"]$/g, "").toLowerCase();
}

export function findFontFamilyOption(value: string | null | undefined): FontFamilyOption | undefined {
  const key = fontFamilyKey(value);
  return key ? FONT_FAMILY_OPTIONS.find((option) => fontFamilyKey(option.value) === key) : undefined;
}

// "14pt" -> "14"; px is converted (96dpi) so a pasted/legacy px size
// still selects the nearest sensible point label.
export function fontSizeToPoints(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = value.trim().match(/^(\d+(?:\.\d+)?)(pt|px)?$/i);
  if (!match) return null;
  const amount = Number(match[1]);
  const points = (match[2] ?? "pt").toLowerCase() === "px" ? (amount * 3) / 4 : amount;
  return String(Math.round(points * 2) / 2);
}

// ---------------------------------------------------------------
// Link URL validation
// ---------------------------------------------------------------

const SAFE_LINK_PROTOCOL = /^(https?:|mailto:)/i;
const ANY_PROTOCOL = /^[a-z][a-z0-9+.-]*:/i;
const EMAIL_ADDRESS = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Normalizes user-entered link text into a safe href, or returns null
 * when it can't be one. Only http(s)/mailto are allowed — the same
 * schemes the backend sanitizer permits on <a href> — so javascript:,
 * data:, vbscript:, file: etc. are rejected outright, never "fixed".
 * A bare "example.com" gets https://, a bare address gets mailto:.
 */
export function normalizeLinkUrl(raw: string): string | null {
  // Control characters/whitespace inside a scheme ("java\tscript:")
  // are a classic filter bypass — strip them before inspecting.
  const value = raw.replace(/[\u0000-\u001F\u007F\s]+/g, "");
  if (!value) return null;
  if (SAFE_LINK_PROTOCOL.test(value)) return value;
  // "example.com:8080/path" looks like a scheme to the pattern above
  // but is really host:port — anything else with a scheme is unsafe.
  if (ANY_PROTOCOL.test(value) && !/^[\w-]+(\.[\w-]+)+:\d+(\/|$)/.test(value)) return null;
  if (EMAIL_ADDRESS.test(value)) return `mailto:${value}`;
  if (/^[\w-]+(\.[\w-]+)+/.test(value) || value.startsWith("//")) {
    return `https://${value.replace(/^\/\//, "")}`;
  }
  return null;
}

/**
 * True when an href already present in content (autolinked text, a
 * pasted/forwarded/signature link) uses a safe scheme. Unlike
 * normalizeLinkUrl this never rewrites — it only accepts or rejects.
 */
export function isSafeLinkHref(href: string): boolean {
  return SAFE_LINK_PROTOCOL.test(href.replace(/[\u0000-\u001F\u007F\s]+/g, ""));
}

// ---------------------------------------------------------------
// Inline-style helpers
// ---------------------------------------------------------------

function parseStyle(style: string | null): Map<string, string> {
  const map = new Map<string, string>();
  if (!style) return map;
  for (const declaration of style.split(";")) {
    const index = declaration.indexOf(":");
    if (index === -1) continue;
    const name = declaration.slice(0, index).trim().toLowerCase();
    const value = declaration.slice(index + 1).trim();
    if (name && value) map.set(name, value);
  }
  return map;
}

function serializeStyle(map: Map<string, string>): string {
  return Array.from(map.entries())
    .map(([name, value]) => `${name}:${value}`)
    .join(";");
}

// Adds each declaration only where the element doesn't already carry
// that property — an author's own alignment/indent/color always wins
// over the defaults being filled in. Idempotent: re-running over
// already-processed HTML (a reopened draft re-sent) changes nothing.
function addDefaultStyles(element: Element, defaults: Record<string, string>) {
  const map = parseStyle(element.getAttribute("style"));
  let changed = false;
  for (const [name, value] of Object.entries(defaults)) {
    if (!map.has(name)) {
      map.set(name, value);
      changed = true;
    }
  }
  if (changed) element.setAttribute("style", serializeStyle(map));
}

function listDepth(list: Element): number {
  let depth = 0;
  let parent = list.parentElement;
  while (parent) {
    if (parent.tagName === "UL" || parent.tagName === "OL") depth++;
    parent = parent.parentElement;
  }
  return depth;
}

function hasTextOrImage(element: Element): boolean {
  if (element.querySelector("img")) return true;
  return (element.textContent ?? "").replace(/ /g, " ").trim().length > 0;
}

const WRAPPER_MARKER = "data-utms-email-body";

// ---------------------------------------------------------------
// Editor HTML -> email HTML
// ---------------------------------------------------------------

/**
 * Turns TipTap's getHTML() output into self-contained email HTML that
 * renders the same in Outlook/Gmail as in the editor:
 *  - one wrapper <div> carrying the default font/size/line-height/color
 *    (an unstyled body falls back to each client's own default font);
 *  - every <p>/<ul>/<ol>/<li>/<blockquote> gets the editor's exact
 *    margins inline (author-set properties such as an indent's
 *    margin-left or text-align are never overwritten);
 *  - nested lists get an explicit list-style-type matching the editor;
 *  - trailing empty paragraphs (TipTap's TrailingNode) are dropped;
 *  - empty paragraphs (a deliberate blank line) get a <br> so they keep
 *    their height — a truly empty <p></p> collapses to nothing in every
 *    client, while the editor shows it as one line;
 *  - a paragraph ending in a Shift+Enter line break gets the extra
 *    <br> ProseMirror itself renders to show that trailing empty line.
 */
export function toEmailHtml(html: string): string {
  if (typeof document === "undefined" || !html.trim()) return html;

  const container = document.createElement("div");
  container.innerHTML = html;

  // Already processed (a reopened draft being re-saved/sent) — unwrap
  // first so the wrapper is never nested inside itself.
  const existing = container.firstElementChild;
  if (container.childElementCount === 1 && existing?.hasAttribute(WRAPPER_MARKER)) {
    container.innerHTML = existing.innerHTML;
  }

  // Empty paragraphs at the very end of the message are not content:
  // TipTap's TrailingNode always keeps one after a closing list/quote/
  // table (so the cursor can leave it), and once filled with a <br>
  // below it would arrive as a stray blank line at the end of the email.
  while (
    container.lastElementChild?.tagName === "P" &&
    container.lastElementChild.childNodes.length === 0 &&
    container.lastChild === container.lastElementChild
  ) {
    container.lastElementChild.remove();
  }

  container.querySelectorAll("p").forEach((paragraph) => {
    const inListItem = paragraph.parentElement?.tagName === "LI";
    addDefaultStyles(paragraph, {
      "margin-top": "0",
      "margin-bottom": inListItem ? "0" : EMAIL_PARAGRAPH_GAP,
    });
    if (!hasTextOrImage(paragraph) && !paragraph.querySelector("br")) {
      paragraph.innerHTML = "<br>";
    } else if (
      paragraph.lastChild?.nodeName === "BR" &&
      paragraph.lastChild.previousSibling?.nodeName !== "BR" &&
      hasTextOrImage(paragraph)
    ) {
      paragraph.appendChild(document.createElement("br"));
    }
  });

  container.querySelectorAll("ul, ol").forEach((list) => {
    const depth = listDepth(list);
    addDefaultStyles(list, {
      "margin-top": "0",
      "margin-bottom": depth === 0 ? EMAIL_PARAGRAPH_GAP : "0",
      "list-style-type": listStyleForDepth(list.tagName === "UL" ? "ul" : "ol", depth),
    });
  });

  container.querySelectorAll("li").forEach((item) => {
    addDefaultStyles(item, { "margin-top": "0", "margin-bottom": "0" });
  });

  container.querySelectorAll("blockquote").forEach((quote) => {
    addDefaultStyles(quote, {
      "margin-top": "0",
      "margin-right": "0",
      "margin-bottom": EMAIL_PARAGRAPH_GAP,
      "margin-left": "0",
      "padding-left": EMAIL_BLOCKQUOTE_PADDING,
      "border-left": EMAIL_BLOCKQUOTE_BORDER,
      color: EMAIL_BLOCKQUOTE_COLOR,
    });
  });

  container.querySelectorAll("a[href]").forEach((link) => {
    addDefaultStyles(link, { color: EMAIL_LINK_COLOR, "text-decoration": "underline" });
  });

  const wrapper = document.createElement("div");
  wrapper.setAttribute(WRAPPER_MARKER, "");
  wrapper.setAttribute(
    "style",
    serializeStyle(
      new Map([
        ["font-family", EMAIL_DEFAULT_FONT_FAMILY],
        ["font-size", EMAIL_DEFAULT_FONT_SIZE],
        ["line-height", EMAIL_LINE_HEIGHT],
        ["color", EMAIL_TEXT_COLOR],
      ])
    )
  );
  wrapper.innerHTML = container.innerHTML;
  return wrapper.outerHTML;
}

/**
 * Inverse of toEmailHtml's two <br> fillers, applied to any HTML
 * loaded INTO the editor (a reopened draft is stored as email HTML —
 * the server sends a saved draft verbatim). Without this, ProseMirror
 * would parse a blank line's filler <br> as a real line break and show
 * every blank line as two. The wrapper <div> and inline margins need
 * no undoing: TipTap's schema has no node for the div and its
 * paragraph node ignores margin-top/margin-bottom.
 */
export function fromEmailHtml(html: string): string {
  if (typeof document === "undefined" || !/<br/i.test(html)) return html;

  const container = document.createElement("div");
  container.innerHTML = html;
  container.querySelectorAll("p").forEach((paragraph) => {
    const children = Array.from(paragraph.childNodes);
    if (children.length === 1 && children[0].nodeName === "BR") {
      paragraph.innerHTML = "";
      return;
    }
    const last = paragraph.lastChild;
    if (last?.nodeName === "BR" && last.previousSibling?.nodeName === "BR" && hasTextOrImage(paragraph)) {
      last.remove();
    }
  });
  return container.innerHTML;
}
