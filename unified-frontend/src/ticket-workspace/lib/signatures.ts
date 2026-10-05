// Composer-side handling of the user's saved email signatures (Profile
// → Settings → Email Signatures; see the backend's EmailSignature
// model). Two distinct concepts live here and must not be confused:
//
//  - The PERMANENT default — server-side (`is_default`), changed only
//    by "Set as default" in Settings.
//  - The CURRENT composer's signature — whatever signature block this
//    one email/draft contains. Picking a different one in the
//    composer's selector only rewrites that block; it never touches
//    the permanent default.
//
// The inserted signature is wrapped in a managed block,
// `<div data-utms-signature="<id>">…</div>` (a real Tiptap node — see
// components/mail/extensions/SignatureBlock.ts — so it survives
// editing and draft save/reopen). That marker is how the composer
// knows exactly which content is "the signature" when switching, so
// only that block is replaced and the user's own text around it is
// never touched. The marker never reaches a recipient: the backend's
// outbound sanitizer allows no data-* attributes, so the wrapper goes
// out as a plain <div>.
//
// Saved signature HTML references images only as `cid:` — an uploaded
// signature image (`cid:sigimg-<hex>`) or the system company logo.
// toEditorSignatureHtml turns those into displayable URLs for the
// editor; resolveInlineImageSources (richText.ts) turns them back into
// `cid:` at save/send, and the backend embeds them as true inline MIME
// parts.

import type { EmailSignatureList } from "@/types";
import { COMPANY_LOGO_CONTENT_ID, COMPANY_LOGO_DISPLAY_SRC, escapeHtml } from "@tw/lib/richText";

export const SIGNATURE_MARKER_ATTR = "data-utms-signature";
// Must stay byte-identical to the backend's
// signature_inline_images.SIGNATURE_IMAGE_CONTENT_ID_PREFIX.
export const SIGNATURE_IMAGE_CONTENT_ID_PREFIX = "sigimg-";
// Marker id for the legacy fallback signature (a user with no saved
// signatures still composes with their pre-existing default).
export const FALLBACK_SIGNATURE_ID = "fallback";

const FORWARD_BANNER_TEXT = "---------- Forwarded message ----------";

export interface ComposerSignatureOption {
  id: string;
  name: string;
  html: string;
  isDefault: boolean;
  isFallback?: boolean;
}

/**
 * The selector's options and the signature a brand-new composer should
 * start with: the user's default, or — only when they have no saved
 * signatures at all — the legacy fallback.
 */
export function composerSignatureOptions(list: EmailSignatureList | undefined): {
  options: ComposerSignatureOption[];
  initial: ComposerSignatureOption | null;
  hasSavedSignatures: boolean;
} {
  if (!list) return { options: [], initial: null, hasSavedSignatures: false };

  const options: ComposerSignatureOption[] = list.signatures.map((s) => ({
    id: s.signature_id,
    name: s.name,
    html: s.html,
    isDefault: s.signature_id === list.default_signature_id,
  }));

  if (options.length === 0 && list.fallback_signature_html) {
    const fallback: ComposerSignatureOption = {
      id: FALLBACK_SIGNATURE_ID,
      name: "Standard signature",
      html: list.fallback_signature_html,
      isDefault: true,
      isFallback: true,
    };
    return { options: [fallback], initial: fallback, hasSavedSignatures: false };
  }

  return {
    options,
    initial: options.find((o) => o.isDefault) ?? null,
    hasSavedSignatures: options.length > 0,
  };
}

function parse(html: string): HTMLDivElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

/**
 * Saved signature HTML -> HTML the editor can display. Each
 * `cid:sigimg-…` image gets its preview URL plus the same
 * data-local-id/data-content-id pair a pasted image carries, which is
 * what lets resolveInlineImageSources turn it back into `cid:` at
 * save/send. The company logo goes to its static asset (also mapped
 * back by resolveInlineImageSources).
 */
export function toEditorSignatureHtml(html: string, imageUrls: Record<string, string>): string {
  if (typeof document === "undefined" || !/<img\b/i.test(html)) return html;

  const container = parse(html);
  container.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") ?? "";
    if (!/^cid:/i.test(src)) return;
    const contentId = src.replace(/^cid:/i, "").toLowerCase();

    if (contentId === COMPANY_LOGO_CONTENT_ID) {
      img.setAttribute("src", COMPANY_LOGO_DISPLAY_SRC);
      return;
    }
    if (contentId.startsWith(SIGNATURE_IMAGE_CONTENT_ID_PREFIX)) {
      img.setAttribute("data-local-id", `sig-${contentId}`);
      img.setAttribute("data-content-id", contentId);
      const url = imageUrls[contentId];
      if (url) img.setAttribute("src", url);
    }
  });
  return container.innerHTML;
}

/** Editor HTML from the Settings signature editor -> HTML to save. */
export function fromEditorSignatureHtml(html: string): string {
  if (typeof document === "undefined" || !/<img\b/i.test(html)) return html;

  const container = parse(html);
  container.querySelectorAll("img").forEach((img) => {
    const contentId = img.getAttribute("data-content-id");
    if (contentId) {
      img.setAttribute("src", `cid:${contentId}`);
    } else if (img.getAttribute("src") === COMPANY_LOGO_DISPLAY_SRC) {
      img.setAttribute("src", `cid:${COMPANY_LOGO_CONTENT_ID}`);
    }
    for (const attr of ["data-local-id", "data-content-id", "data-attachment-id", "data-upload-status"]) {
      img.removeAttribute(attr);
    }
  });
  return container.innerHTML;
}

/** The managed, marked block for one signature, ready for the editor. */
export function buildSignatureBlockHtml(
  signature: Pick<ComposerSignatureOption, "id" | "html">,
  imageUrls: Record<string, string>
): string {
  return (
    `<div ${SIGNATURE_MARKER_ATTR}="${escapeHtml(signature.id)}">` +
    `${toEditorSignatureHtml(signature.html, imageUrls)}</div>`
  );
}

/** The id of the signature currently in this body, or null if none. */
export function findSignatureId(bodyHtml: string): string | null {
  if (typeof document === "undefined" || !bodyHtml.includes(SIGNATURE_MARKER_ATTR)) return null;
  const block = parse(bodyHtml).querySelector(`[${SIGNATURE_MARKER_ATTR}]`);
  return block ? block.getAttribute(SIGNATURE_MARKER_ATTR) : null;
}

function findForwardBanner(container: HTMLElement): Element | null {
  return (
    Array.from(container.children).find(
      (child) => child.tagName === "P" && child.textContent?.trim() === FORWARD_BANNER_TEXT
    ) ?? null
  );
}

/**
 * Swaps the managed signature block for `blockHtml` (or removes it when
 * null) and leaves everything else in the body exactly as it was.
 * With no existing block, a new one goes where the composer would have
 * put it: above a forwarded message's banner, otherwise at the end of
 * the user's text (Reply/Reply All quoting is appended by Graph below
 * the whole body, so the end of the body is already above the quote).
 */
export function replaceSignatureBlock(bodyHtml: string, blockHtml: string | null): string {
  if (typeof document === "undefined") return bodyHtml;

  const container = parse(bodyHtml);
  const existing = container.querySelector(`[${SIGNATURE_MARKER_ATTR}]`);
  const replacement = blockHtml ? parse(blockHtml).firstElementChild : null;

  if (existing) {
    if (replacement) existing.replaceWith(replacement);
    else existing.remove();
    return container.innerHTML;
  }

  if (!replacement) return bodyHtml;

  const banner = findForwardBanner(container);
  if (banner) {
    banner.before(replacement);
    return container.innerHTML;
  }

  // Keep a leading empty line for the user's own text when the body is
  // otherwise empty — the same shape buildInitialBodyHtml produces.
  if (!container.textContent?.trim() && !container.querySelector("img")) {
    return `<p></p>${replacement.outerHTML}`;
  }
  container.appendChild(replacement);
  return container.innerHTML;
}

/**
 * The managed signature images in a body, as pseudo-attachments for
 * resolveCidImagesForEditing — a reopened draft stores them as `cid:`
 * references that only the signatures query (not the draft's own
 * attachment list) knows how to display.
 */
export function signatureImagePreviewAttachments(
  imageUrls: Record<string, string>
): Array<{ content_id: string; preview_url: string }> {
  return Object.entries(imageUrls).map(([content_id, preview_url]) => ({ content_id, preview_url }));
}
