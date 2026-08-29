// Tiptap gives us HTML for a pleasant authoring experience (bold/
// italic/lists/links), but every existing mail/ticket endpoint this
// app already has (`reply`, `draft`, `compose`) stores a plain-text
// `message`/`body` string — the ticket timeline, Sent list, and
// Interactions page all render that field as plain text. Sending raw
// HTML into it would look broken everywhere except the page being
// rebuilt here, so every send/save path converts to plain text first.

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function htmlToPlainText(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|blockquote)>/gi, "\n")
    .replace(/<li>/gi, "• ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// Message bodies are stored as plain text (see note above), so reading
// them back needs its own light HTML-ification — escape first, then
// wrap recognizable URLs/email addresses in real anchors, so links in
// a received email are actually clickable instead of inert text. Single
// combined pattern (not two separate escape+replace passes) so a URL
// containing "@" can't get double-wrapped by a second, narrower email
// match run over its own (already-anchored) output.
const LINK_PATTERN = /(https?:\/\/[^\s<]+[^\s<.,:;!?'")\]]|[\w.+-]+@[\w-]+\.[\w.-]+)/g;

export function linkifyPlainText(text: string): string {
  const escaped = escapeHtml(text);
  return escaped
    .replace(LINK_PATTERN, (match) =>
      /^https?:\/\//i.test(match)
        ? `<a href="${match}" target="_blank" rel="noreferrer" class="break-all text-primary underline">${match}</a>`
        : `<a href="mailto:${match}" class="break-all text-primary underline">${match}</a>`
    )
    .replace(/\n/g, "<br/>");
}

// Cheap tag-presence check, not a parse — used to decide whether a
// composer's HTML body is worth sending alongside the plain-text
// `message` field as a real `body_html` (Outlook-style clipboard
// paste: pasted tables/images/formatting), or whether the message is
// genuinely plain and sending body_html at all would be a pointless
// redundant field. A false positive just means "sent body_html when
// plain text alone would've done" — harmless, so a simple tag check
// is deliberately preferred over anything more precise.
const RICH_CONTENT_TAG_PATTERN = /<(a|img|table|strong|b|em|i|u|ul|ol|blockquote)\b/i;

export function isRichContent(html: string): boolean {
  return RICH_CONTENT_TAG_PATTERN.test(html);
}

// Cheap substring check, re-run on every editor update (see
// RichTextEditor.tsx) rather than tracked as separate counter state —
// deliberately self-correcting: deleting the broken image node from
// the document makes this false again on the very next keystroke,
// with no "stuck forever" risk a manually-incremented/decremented
// failure counter would have. A failed upload (oversized file,
// network error, or no upload wiring at all for this composer) must
// never be silently dropped from the sent message the way
// resolveInlineImageSources otherwise would — composers block Send
// while this is true, same as a still-in-flight upload.
export function hasFailedImageUpload(html: string): boolean {
  return /data-upload-status="error"/.test(html);
}

// Pasted screenshots are inserted into the Tiptap document with a
// local blob: preview (see clipboardPaste.ts) and, once the
// background upload resolves, a `data-content-id` attribute carrying
// the real backend-minted content_id. `blob:` URLs are meaningless
// outside this browser tab — before a body_html is ever sent to the
// backend, every such <img>'s `src` must be rewritten to the real
// `cid:{content_id}` reference the backend/Graph can actually
// resolve. A pasted image with no data-content-id (upload failed, or
// this composer has no upload wiring at all — see RichTextEditor's
// onImageUpload prop) is removed entirely rather than sent with a
// dead blob: reference no recipient could ever resolve.

// A pasted image's interaction_id (tracked by every composer so it
// can be submitted back as `inline_image_interaction_ids` at Send —
// see resolveInlineImageSources above) is recorded the moment the
// upload succeeds, but the image itself can be deleted/replaced/
// undone in the editor afterward, before Send. Nothing else ever
// prunes that tracked id, so by Send time it can reference an image
// that no longer has any `cid:` anchor anywhere in the body actually
// being sent. filterLiveInlineImageIds is the fix: called right
// before building the send payload, it keeps only the ids whose own
// contentId still appears as `cid:{contentId}` in the exact
// resolveInlineImageSources output being sent — the same body the
// backend itself will also check (InteractionService.
// _finalize_envelope_attachments), so a stale id is never submitted
// in the first place instead of relying solely on that backend
// safety net.
export interface TrackedInlineImage {
  interactionId: string;
  contentId: string;
}

export function filterLiveInlineImageIds(
  resolvedBodyHtml: string,
  tracked: TrackedInlineImage[]
): string[] {
  return tracked
    .filter((image) => resolvedBodyHtml.includes(`cid:${image.contentId}`))
    .map((image) => image.interactionId);
}

export function resolveInlineImageSources(html: string): string {
  if (typeof document === "undefined") return html;

  const container = document.createElement("div");
  container.innerHTML = html;

  container.querySelectorAll("img[data-local-id]").forEach((img) => {
    const contentId = img.getAttribute("data-content-id");
    if (contentId) {
      img.setAttribute("src", `cid:${contentId}`);
    } else {
      img.remove();
    }
  });

  return container.innerHTML;
}

// The inverse of resolveInlineImageSources: that one rewrites a local
// blob: preview into `cid:{content_id}` right before SENDING (the
// only reference Graph/a real email client can resolve). A `cid:` URL
// means nothing to a plain web browser, though — there is no MIME
// message here for it to resolve against — so before this app's own
// read views (Mail thread bubbles, Ticket Timeline, Interaction
// details) render a stored body_html back via dangerouslySetInnerHTML,
// every `cid:` reference must be swapped for that attachment's real,
// presigned download/preview URL, found by matching content_id
// against the message's own already-fetched attachment list (no
// extra request — every AttachmentMeta already carries content_id).
// Mirrors the backend's _normalize_content_id (mail_mapping_service.py):
// URL-decode, strip surrounding <>, lowercase — so a real sender's cid:
// text that differs from Graph's stored contentId only by case, bracket
// presence, or percent-encoding still resolves, per RFC 2392.
function normalizeContentId(raw: string): string {
  let decoded = raw;
  try {
    decoded = decodeURIComponent(raw);
  } catch {
    // Malformed percent-encoding must never throw and break the rest
    // of the message's render — fall back to the raw value.
  }
  return decoded.trim().replace(/^<|>$/g, "").toLowerCase();
}

export function resolveCidImagesForDisplay(
  html: string,
  attachments: Array<{ content_id?: string | null; download_url?: string; preview_url?: string | null }>
): string {
  if (typeof document === "undefined" || !html.includes("cid:")) return html;

  const byContentId = new Map(
    attachments
      .filter((a) => a.content_id)
      .map((a) => [normalizeContentId(a.content_id as string), a])
  );

  const container = document.createElement("div");
  container.innerHTML = html;

  container.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") ?? "";
    if (!/^cid:/i.test(src)) return;
    const attachment = byContentId.get(normalizeContentId(src.replace(/^cid:/i, "")));
    if (attachment) {
      img.setAttribute("src", attachment.preview_url || attachment.download_url || "");
      return;
    }
    // No attachment in this message's own list carries this content_id
    // (e.g. an inline image the mail pipeline never captured as a real
    // Attachment row) — `cid:` is not a scheme any browser can fetch,
    // so leaving it as the <img> src always renders a native broken-
    // image icon with no possible network request to retry. Swap it
    // for an inert inline placeholder instead of a guaranteed-broken
    // <img> element.
    const placeholder = document.createElement("span");
    placeholder.textContent = "[image unavailable]";
    placeholder.style.cssText =
      "display:inline-block;padding:1px 6px;border-radius:4px;background:var(--muted,#f1f5f9);color:var(--muted-foreground,#64748b);font-size:11px;font-style:italic;";
    img.replaceWith(placeholder);
  });

  return container.innerHTML;
}

// Shared Tailwind arbitrary-variant classes for a container rendering
// a message's real body_html via dangerouslySetInnerHTML (Mail thread
// bubbles, Ticket Timeline, Interaction details, the full-page
// Interaction view) — mirrors RichTextEditor.tsx's own compose-time
// table/image styling so a pasted table/screenshot looks the same
// (visible grid lines, sane image sizing) whether it's being composed
// or read back. A bare <table>/<img> has no built-in visual styling
// at all, so without this a real table renders with no grid lines —
// easy to mistake for "not formatted".
//
// Also carries the same <p>/<ul>/<ol>/<li>/<blockquote>/heading reset
// RichTextEditor.tsx's own editorProps.attributes.class already applies
// at compose time, for the same reason: Tailwind's global Preflight
// base styles zero list-style/margin/padding on every <ul>/<ol>/<li>/<p>
// on the page (not just here), so a real <ol><li> list rendered with no
// numbering, no indentation, and no spacing between paragraphs — a
// semantically-intact message looking like a flattened wall of text.
// This container never had the compose-side's counterpart reset.
//
// Deliberately excludes any border/grid styling — those live in
// RENDERED_MESSAGE_TABLE_BORDER_CLASS below and must only be applied
// to agent-authored content, never inbound sender HTML. See that
// constant's own comment for why.
export const RENDERED_MESSAGE_HTML_CLASS =
  "[&_table]:my-2 [&_table]:max-w-full [&_td]:p-1.5 [&_td]:align-top [&_th]:p-1.5 [&_th]:text-left [&_th]:font-semibold [&_img]:mb-2 [&_img]:max-w-full [&_img]:rounded [&_a]:break-all [&_a]:underline [&_a]:text-primary [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:mb-1 [&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_h1]:mb-2 [&_h1]:mt-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-3 [&_h3]:text-base [&_h3]:font-semibold [&_h4]:mb-1 [&_h4]:mt-2 [&_h4]:font-semibold [&_h5]:mb-1 [&_h5]:mt-2 [&_h5]:font-semibold [&_h6]:mb-1 [&_h6]:mt-2 [&_h6]:font-semibold";

// Draws a visible grid (borders + header background) around every
// <td>/<th>. Only safe to add for agent-authored content (a composer
// paste, a reply, an internal note) where a <table> is always a
// deliberate data table someone pasted in — never for inbound sender
// HTML, where a <table> is just as often pure layout/positioning
// markup (newsletter/transactional templates nest tables purely to
// lay out paragraphs/sections, with no intent for any of it to look
// like a bordered grid). This mirrors the exact same inbound/outbound
// line html_sanitizer.py's sanitize_inbound_html already draws at the
// HTML-sanitization layer, for the same reason: forcing a border onto
// every nested layout table made ordinary transactional/notification
// emails render as a wall of boxes never present in the original
// message (confirmed against a real inbound TMHP IAMOnline
// verification email — every paragraph is its own layout <td>).
export const RENDERED_MESSAGE_TABLE_BORDER_CLASS =
  "[&_table]:border-collapse [&_td]:border [&_td]:border-border [&_th]:border [&_th]:border-border [&_th]:bg-muted";

export function plainTextToHtml(text: string): string {
  if (!text) return "";
  return text
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br/>")}</p>`)
    .join("");
}

// Outlook's own inline reply/forward chrome — when a sender replies or
// forwards "inline" (not as an attachment), Outlook inserts a plain
// From:/Sent:/To:/[Cc:/Bcc:]/Subject: block directly into the message
// body's own HTML (a real, distinctive `<div id="divRplyFwdMsg">`
// container, confirmed against this app's own stored inbound mail).
// _html_to_plain_text (backend) flattens that block into plain text
// with no awareness of it, so it survives verbatim into the stored
// body.
//
// This is a line-based scanner, not one big regex: each label must be
// alone on its own line, immediately followed by its value on the
// very next line, in this exact fixed order — the shape actually
// observed in this app's stored mail. That specificity is what keeps
// it safe: genuine prose containing the word "From" never matches,
// since real writing doesn't put these four-to-six labels alone on
// consecutive lines in this exact sequence.
const REQUIRED_LABEL_SEQUENCE = ["From:", "Sent:", "To:"];
const OPTIONAL_LABELS = ["Cc:", "Bcc:"];
const FINAL_LABEL = "Subject:";

function isBlankFillerLine(line: string): boolean {
  // Outlook pads the space between the quoted header and the real
  // content with lines that are empty, or contain only whitespace/a
  // lone non-breaking space ( ) — never real content.
  return line.replace(/ /g, "").trim() === "";
}

export interface QuoteHeaderFields {
  from: string;
  sent: string;
  to: string;
  cc?: string;
  bcc?: string;
  subject: string;
}

// Tries to match one quoted-header block starting exactly at `start`,
// capturing each label's value alongside the label sequence itself.
// Returns the index to resume scanning from (past the block and its
// trailing filler lines) plus the captured fields, or null if `start`
// isn't the beginning of one.
function matchQuotedHeaderBlock(
  lines: string[],
  start: number
): { resumeAt: number; fields: QuoteHeaderFields } | null {
  let i = start;
  const values: Record<string, string> = {};

  for (const label of REQUIRED_LABEL_SEQUENCE) {
    if (lines[i]?.trim() !== label) return null;
    if (lines[i + 1] === undefined || lines[i + 1].trim() === "") return null; // must have a value
    values[label] = lines[i + 1].trim();
    i += 2;
  }

  for (const label of OPTIONAL_LABELS) {
    if (lines[i]?.trim() === label && lines[i + 1]?.trim() !== "") {
      values[label] = lines[i + 1].trim();
      i += 2;
    }
  }

  if (lines[i]?.trim() !== FINAL_LABEL) return null;
  if (lines[i + 1] === undefined || lines[i + 1].trim() === "") return null;
  values[FINAL_LABEL] = lines[i + 1].trim();
  i += 2;

  while (i < lines.length && isBlankFillerLine(lines[i])) {
    i++;
  }

  return {
    resumeAt: i,
    fields: {
      from: values["From:"],
      sent: values["Sent:"],
      to: values["To:"],
      cc: values["Cc:"],
      bcc: values["Bcc:"],
      subject: values["Subject:"],
    },
  };
}

// A header value is typically "Name <email@domain>" — pull the email
// out when present, since that's the more reliable identity signal
// (a display name can be spelled/cased differently across messages).
function extractEmail(value: string): string | null {
  const match = value.match(/<([^>]+)>/);
  return match ? match[1].trim().toLowerCase() : null;
}

function isSameSender(fromValue: string, currentSender: { name: string; email: string | null }): boolean {
  const quotedEmail = extractEmail(fromValue);
  if (quotedEmail && currentSender.email) {
    return quotedEmail === currentSender.email.trim().toLowerCase();
  }
  const quotedName = (quotedEmail ? fromValue.slice(0, fromValue.indexOf("<")) : fromValue).trim().toLowerCase();
  return quotedName === currentSender.name.trim().toLowerCase();
}

export interface ParsedQuoteSegment {
  header: QuoteHeaderFields;
  body: string;
}

// Splits a message body into its genuinely new leading text plus zero
// or more embedded quote sections. A quote-header block whose From:
// matches this same bubble's own card-header sender is dropped
// entirely (that older message already has its own separate bubble
// earlier in the same thread, so re-showing its header would just
// duplicate what the card already displays) — everything else is kept
// as its own distinct section so a genuinely different party's quoted
// message stays visible, Outlook-style, instead of being flattened
// into an undifferentiated wall of text.
export function parseMessageIntoQuotes(
  body: string,
  currentSender: { name: string; email: string | null }
): { leading: string; quotes: ParsedQuoteSegment[] } {
  if (!body) return { leading: body, quotes: [] };

  const lines = body.split("\n");
  const quotes: { header: QuoteHeaderFields; bodyLines: string[] }[] = [];
  const leadingLines: string[] = [];
  let activeBucket: string[] = leadingLines;
  let i = 0;

  while (i < lines.length) {
    const match = matchQuotedHeaderBlock(lines, i);
    if (match) {
      if (!isSameSender(match.fields.from, currentSender)) {
        activeBucket = [];
        quotes.push({ header: match.fields, bodyLines: activeBucket });
      }
      i = match.resumeAt;
      continue;
    }
    activeBucket.push(lines[i]);
    i++;
  }

  return {
    leading: leadingLines.join("\n"),
    quotes: quotes.map((q) => ({ header: q.header, body: q.bodyLines.join("\n") })),
  };
}

function renderQuoteHeaderHtml(header: QuoteHeaderFields): string {
  const e = escapeHtml;
  const lines = [
    `<strong>From:</strong> ${e(header.from)}`,
    `<strong>Sent:</strong> ${e(header.sent)}`,
    `<strong>To:</strong> ${e(header.to)}`,
  ];
  if (header.cc) lines.push(`<strong>Cc:</strong> ${e(header.cc)}`);
  if (header.bcc) lines.push(`<strong>Bcc:</strong> ${e(header.bcc)}`);
  lines.push(`<strong>Subject:</strong> ${e(header.subject)}`);
  return lines.join("<br/>");
}

// Renders a message body the way Outlook itself shows a threaded
// reply chain: the sender's own new text first, then each genuinely
// different quoted message as its own clearly delineated section
// (bold header labels, a top border, slightly indented/muted) — see
// parseMessageIntoQuotes for the self-vs-other-sender split this
// relies on.
export function renderThreadedMessageHtml(
  body: string,
  currentSender: { name: string; email: string | null }
): string {
  const { leading, quotes } = parseMessageIntoQuotes(body, currentSender);
  let html = linkifyPlainText(leading);

  for (const quote of quotes) {
    html +=
      `<div style="margin-top:10px;padding-top:8px;border-top:1px solid var(--border, #e5e7eb);">` +
      `<div style="font-size:11px;line-height:1.6;color:var(--muted-foreground, #6b7280);">${renderQuoteHeaderHtml(quote.header)}</div>` +
      `<div style="margin-top:6px;">${linkifyPlainText(quote.body)}</div>` +
      `</div>`;
  }

  return html;
}

export function buildForwardHtml(params: {
  fromLabel: string;
  dateLabel: string;
  subject: string;
  body: string;
  // The original message's real HTML body (already sanitized server-
  // side), when one exists — preferred verbatim over `body` (the
  // plain-text-flattened field) so tables/formatting survive into the
  // forwarded message, mirroring MessageDetailsView's own Bubble
  // rendering, which already prefers body_html over body the same
  // way. Falls back to escaping `body` as plain text when absent.
  bodyHtml?: string;
}): string {
  const { fromLabel, dateLabel, subject, body, bodyHtml } = params;
  const quotedContent = bodyHtml
    ? bodyHtml
    : escapeHtml(body).replace(/\n/g, "<br/>");
  return (
    `<p></p><p>---------- Forwarded message ----------</p>` +
    `<p>From: ${escapeHtml(fromLabel)}<br/>Date: ${escapeHtml(dateLabel)}<br/>Subject: ${escapeHtml(subject)}</p>` +
    `<blockquote>${quotedContent}</blockquote>`
  );
}
