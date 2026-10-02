import { describe, expect, it } from "vitest";

import { buildInitialBodyHtml, resolveCidImagesForEditing, resolveInlineImageSources } from "@tw/lib/richText";

const attachments = [
  { content_id: "abc123", download_url: "https://s/dl", preview_url: "https://s/preview-abc" },
  { content_id: "<DEF456>", download_url: "https://s/dl-def", preview_url: null },
];

function srcs(html: string) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return Array.from(div.querySelectorAll("img")).map((i) => i.getAttribute("src"));
}

describe("resolveCidImagesForEditing (reopened draft)", () => {
  it("swaps a cid: reference for the attachment's preview URL", () => {
    const html = '<p><img src="cid:abc123" data-local-id="l1" data-content-id="abc123"></p>';
    expect(srcs(resolveCidImagesForEditing(html, attachments))).toEqual(["https://s/preview-abc"]);
  });

  it("falls back to the download URL and matches content ids like the display resolver (case, brackets)", () => {
    expect(srcs(resolveCidImagesForEditing('<img src="cid:def456">', attachments))).toEqual(["https://s/dl-def"]);
  });

  it("restores the company logo from its stored cid: back to the static asset the editor displays", () => {
    // The signature block's own display src, as the composer prefills it.
    const displayHtml = buildInitialBodyHtml({ signatureHtml: "<p>Regards</p>" });
    const displaySrc = srcs(displayHtml).find(Boolean)!;
    const stored = resolveInlineImageSources(displayHtml);
    const cidSrc = srcs(stored).find((s) => s?.startsWith("cid:"))!;
    expect(cidSrc).toBeTruthy();
    expect(srcs(resolveCidImagesForEditing(stored, []))).toContain(displaySrc);
  });

  it("leaves an unresolvable image untouched instead of rewriting the draft", () => {
    expect(srcs(resolveCidImagesForEditing('<img src="cid:missing">', attachments))).toEqual(["cid:missing"]);
  });

  it("leaves non-cid images and html without images alone", () => {
    const plain = "<p>hello</p>";
    expect(resolveCidImagesForEditing(plain, attachments)).toBe(plain);
    expect(srcs(resolveCidImagesForEditing('<img src="https://x/y.png">', attachments))).toEqual(["https://x/y.png"]);
  });

  it("round-trips: a restored image becomes cid: again on the next save", () => {
    const saved = '<p><img src="cid:abc123" data-local-id="l1" data-content-id="abc123"></p>';
    const restored = resolveCidImagesForEditing(saved, attachments);
    expect(srcs(resolveInlineImageSources(restored))).toEqual(["cid:abc123"]);
  });
});
