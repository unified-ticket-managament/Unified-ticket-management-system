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

export function plainTextToHtml(text: string): string {
  if (!text) return "";
  return text
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br/>")}</p>`)
    .join("");
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
