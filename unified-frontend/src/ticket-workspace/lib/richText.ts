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
}): string {
  const { fromLabel, dateLabel, subject, body } = params;
  return (
    `<p></p><p>---------- Forwarded message ----------</p>` +
    `<p>From: ${escapeHtml(fromLabel)}<br/>Date: ${escapeHtml(dateLabel)}<br/>Subject: ${escapeHtml(subject)}</p>` +
    `<blockquote>${escapeHtml(body).replace(/\n/g, "<br/>")}</blockquote>`
  );
}
