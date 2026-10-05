import { Editor } from "@tiptap/core";
import { describe, expect, it } from "vitest";

import { createRichTextExtensions } from "@tw/components/mail/RichTextEditor";
import {
  buildForwardHtml,
  buildInitialBodyHtml,
  buildOutgoingBodyHtml,
  COMPANY_LOGO_CONTENT_ID,
  resolveCidImagesForEditing,
} from "@tw/lib/richText";
import {
  FALLBACK_SIGNATURE_ID,
  buildSignatureBlockHtml,
  composerSignatureOptions,
  findSignatureId,
  fromEditorSignatureHtml,
  replaceSignatureBlock,
  signatureImagePreviewAttachments,
  toEditorSignatureHtml,
} from "@tw/lib/signatures";
import type { EmailSignature, EmailSignatureList } from "@/types";

const PROBE_IMG = "sigimg-" + "a".repeat(32);
const PARTNER_IMG = "sigimg-" + "b".repeat(32);
const IMAGE_URLS = {
  [PROBE_IMG]: "https://storage.test/probe.png",
  [PARTNER_IMG]: "https://storage.test/partner.png",
};
const LOGO_BLOCK = `<div><img src="cid:${COMPANY_LOGO_CONTENT_ID}" alt="Probe Practice Solutions" width="150"></div>`;

function sig(id: string, name: string, html: string, isDefault = false): EmailSignature {
  return {
    signature_id: id,
    name,
    html,
    is_default: isDefault,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const PROBE = sig("s1", "Probe Practice", `<p>Regards,<br>Hari</p><p><img src="cid:${PROBE_IMG}" width="120"></p>`, true);
const PARTNER = sig("s2", "Partner Company", `<p>Regards,<br>Hari</p><p><img src="cid:${PARTNER_IMG}" width="120"></p>`);
const PLAIN = sig("s3", "Plain", "<p>Thanks,<br>Hari</p>");

const LIST: EmailSignatureList = {
  signatures: [PROBE, PARTNER, PLAIN],
  default_signature_id: "s1",
  fallback_signature_html: null,
  image_urls: IMAGE_URLS,
};

const blockFor = (s: EmailSignature) => buildSignatureBlockHtml({ id: s.signature_id, html: s.html }, IMAGE_URLS);

describe("composerSignatureOptions", () => {
  it("starts with the permanent default and marks it", () => {
    const { options, initial, hasSavedSignatures } = composerSignatureOptions(LIST);
    expect(options.map((o) => o.name)).toEqual(["Probe Practice", "Partner Company", "Plain"]);
    expect(initial?.id).toBe("s1");
    expect(options.find((o) => o.isDefault)?.id).toBe("s1");
    expect(hasSavedSignatures).toBe(true);
  });

  it("follows a changed default (Set as default in Settings)", () => {
    const { initial } = composerSignatureOptions({ ...LIST, default_signature_id: "s2" });
    expect(initial?.id).toBe("s2");
  });

  it("falls back to the legacy signature when nothing is saved", () => {
    const { options, initial, hasSavedSignatures } = composerSignatureOptions({
      signatures: [],
      default_signature_id: null,
      fallback_signature_html: "<div>Regards,<br>Kamal</div>" + LOGO_BLOCK,
      image_urls: {},
    });
    expect(hasSavedSignatures).toBe(false);
    expect(initial?.id).toBe(FALLBACK_SIGNATURE_ID);
    expect(options).toHaveLength(1);
  });

  it("offers nothing (no broken dropdown entries) with no signatures and no fallback", () => {
    const result = composerSignatureOptions({
      signatures: [],
      default_signature_id: null,
      fallback_signature_html: null,
      image_urls: {},
    });
    expect(result.options).toEqual([]);
    expect(result.initial).toBeNull();
  });
});

describe("managed signature block", () => {
  it("new email / reply body is the cursor line plus the marked default signature", () => {
    const body = buildInitialBodyHtml({ signatureBlockHtml: blockFor(PROBE) });
    expect(body.startsWith("<p></p>")).toBe(true);
    expect(findSignatureId(body)).toBe("s1");
  });

  it("changing signature replaces the block instead of appending a second one", () => {
    const typed =
      "<p>Hello,</p><p>Please find the details below.</p>" + blockFor(PROBE);

    const swapped = replaceSignatureBlock(typed, blockFor(PARTNER));

    expect(findSignatureId(swapped)).toBe("s2");
    expect(swapped).toContain(IMAGE_URLS[PARTNER_IMG]);
    expect(swapped).not.toContain(IMAGE_URLS[PROBE_IMG]);
    expect((swapped.match(/data-utms-signature=/g) ?? []).length).toBe(1);
    expect((swapped.match(/Regards,/g) ?? []).length).toBe(1);
    // The user's own text is untouched.
    expect(swapped.startsWith("<p>Hello,</p><p>Please find the details below.</p>")).toBe(true);
  });

  it("only the managed block is replaced — user text that looks like a signature stays", () => {
    const typed = "<p>Regards,<br>Hari (typed by hand)</p>" + blockFor(PROBE);
    const swapped = replaceSignatureBlock(typed, blockFor(PLAIN));
    expect(swapped).toContain("Hari (typed by hand)");
    expect(swapped).toContain("Thanks,");
    expect(swapped).not.toContain(PROBE_IMG);
  });

  it("choosing No signature removes only the block", () => {
    const typed = "<p>Hello</p>" + blockFor(PROBE);
    expect(replaceSignatureBlock(typed, null)).toBe("<p>Hello</p>");
  });

  it("forward: the signature goes above the forwarded-message banner, never inside the quote", () => {
    const forward = buildForwardHtml({
      fromLabel: "John <john@client.test>",
      dateLabel: "Mon",
      subject: "Claim",
      body: "Original text",
    });
    const withSig = replaceSignatureBlock(forward, blockFor(PROBE));
    const sigAt = withSig.indexOf("data-utms-signature");
    expect(sigAt).toBeGreaterThan(-1);
    expect(sigAt).toBeLessThan(withSig.indexOf("---------- Forwarded message ----------"));
    expect(sigAt).toBeLessThan(withSig.indexOf("<blockquote>"));

    const swapped = replaceSignatureBlock(withSig, blockFor(PARTNER));
    expect(findSignatureId(swapped)).toBe("s2");
    expect(swapped.indexOf("data-utms-signature")).toBeLessThan(swapped.indexOf("Forwarded message"));
  });

  it("re-adding a removed signature puts it after the user's text", () => {
    const body = "<p>My reply</p>";
    const out = replaceSignatureBlock(body, blockFor(PLAIN));
    expect(out.startsWith("<p>My reply</p>")).toBe(true);
    expect(findSignatureId(out)).toBe("s3");
  });

  it("survives the real editor (and edits around it) so a reopened draft keeps its selection", () => {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: createRichTextExtensions(),
      content: buildInitialBodyHtml({ signatureBlockHtml: blockFor(PARTNER) }),
    });
    editor.commands.focus("start");
    editor.chain().insertContent("Typed text").run();
    const html = editor.getHTML();
    editor.destroy();

    expect(findSignatureId(html)).toBe("s2");
    // A saved draft is this same HTML run through buildOutgoingBodyHtml.
    const draft = buildOutgoingBodyHtml(html)!;
    expect(findSignatureId(draft)).toBe("s2");
    expect(findSignatureId(replaceSignatureBlock(draft, blockFor(PLAIN)))).toBe("s3");
  });
});

describe("signature images", () => {
  it("shows uploaded images and the company logo in the editor, and sends them as cid:", () => {
    const editorHtml = toEditorSignatureHtml(
      `<p>Regards</p><p><img src="cid:${PROBE_IMG}"> <img src="cid:${PARTNER_IMG}"></p>${LOGO_BLOCK}`,
      IMAGE_URLS
    );
    expect(editorHtml).toContain(`src="${IMAGE_URLS[PROBE_IMG]}"`);
    expect(editorHtml).toContain(`src="${IMAGE_URLS[PARTNER_IMG]}"`);
    expect(editorHtml).toContain('src="/probe-practice-solutions-logo.jpg"');
    expect(editorHtml).not.toContain("cid:");

    const sent = buildOutgoingBodyHtml(`<p>Hello</p><div data-utms-signature="s1">${editorHtml}</div>`)!;
    expect(sent).toContain(`src="cid:${PROBE_IMG}"`);
    expect(sent).toContain(`src="cid:${PARTNER_IMG}"`);
    expect(sent).toContain(`src="cid:${COMPANY_LOGO_CONTENT_ID}"`);
    expect(sent).not.toContain("storage.test");
    expect(sent).not.toContain("localhost");
  });

  it("Settings editor round trip saves only cid references and no editor bookkeeping", () => {
    const original = `<p>Regards</p><p><img src="cid:${PROBE_IMG}" width="120"></p>${LOGO_BLOCK}`;
    const saved = fromEditorSignatureHtml(toEditorSignatureHtml(original, IMAGE_URLS));
    expect(saved).toContain(`src="cid:${PROBE_IMG}"`);
    expect(saved).toContain(`src="cid:${COMPANY_LOGO_CONTENT_ID}"`);
    expect(saved).not.toContain("data-");
    expect(saved).not.toContain("https://");
  });

  it("a freshly pasted (blob:) signature image is saved as its uploaded cid", () => {
    const pasted = `<p><img src="blob:http://localhost/123" data-local-id="l1" data-content-id="${PARTNER_IMG}"></p>`;
    expect(fromEditorSignatureHtml(pasted)).toBe(`<p><img src="cid:${PARTNER_IMG}"></p>`);
  });

  it("a reopened draft's stored signature images resolve back to previews", () => {
    const stored = `<div data-utms-signature="s1"><p><img src="cid:${PROBE_IMG}" data-local-id="sig-${PROBE_IMG}" data-content-id="${PROBE_IMG}"></p></div>`;
    const reopened = resolveCidImagesForEditing(stored, signatureImagePreviewAttachments(IMAGE_URLS));
    expect(reopened).toContain(`src="${IMAGE_URLS[PROBE_IMG]}"`);
    expect(buildOutgoingBodyHtml(reopened)).toContain(`src="cid:${PROBE_IMG}"`);
  });
});
