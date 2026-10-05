import { describe, expect, it } from "vitest";

import {
  EMAIL_DEFAULT_FONT_FAMILY,
  findFontFamilyOption,
  fontSizeToPoints,
  fromEmailHtml,
  isSafeLinkHref,
  normalizeLinkUrl,
  toEmailHtml,
} from "@tw/lib/emailHtml";
import { buildInitialBodyHtml, buildOutgoingBodyHtml, COMPANY_LOGO_CONTENT_ID } from "@tw/lib/richText";
import { buildSignatureBlockHtml } from "@tw/lib/signatures";

function parse(html: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

describe("toEmailHtml — editor HTML to email-safe HTML", () => {
  it("wraps the body in the default Times New Roman 11pt font", () => {
    const wrapper = parse(toEmailHtml("<p>Hello</p>")).firstElementChild as HTMLElement;
    expect(wrapper.tagName).toBe("DIV");
    const style = wrapper.getAttribute("style") ?? "";
    expect(style).toContain(`font-family:${EMAIL_DEFAULT_FONT_FAMILY}`);
    expect(style).toContain("font-size:11pt");
    expect(style).toContain("line-height:1.35");
  });

  it("inlines the editor's controlled paragraph gap instead of client defaults", () => {
    const paragraphs = parse(toEmailHtml("<p>One</p><p>Two</p>")).querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    paragraphs.forEach((p) => {
      expect(p.getAttribute("style")).toBe("margin-top:0;margin-bottom:10px");
    });
  });

  it("never turns visual line wrapping into <br> — a long paragraph stays one paragraph", () => {
    const long = "We have received your request and reviewed the information provided by your team. ".repeat(6);
    const out = toEmailHtml(`<p>${long}</p>`);
    expect(out).not.toContain("<br");
    expect(parse(out).querySelectorAll("p")).toHaveLength(1);
  });

  it("keeps an intentionally blank paragraph visible with a single <br> filler", () => {
    const paragraphs = parse(toEmailHtml("<p>Hello</p><p></p><p>Bye</p>")).querySelectorAll("p");
    expect(paragraphs[1].innerHTML).toBe("<br>");
  });

  it("mirrors ProseMirror's trailing-break line for a paragraph ending in Shift+Enter", () => {
    const p = parse(toEmailHtml("<p>Regards,<br></p>")).querySelector("p")!;
    expect(p.innerHTML).toBe("Regards,<br><br>");
    // A soft break in the middle is untouched.
    const mid = parse(toEmailHtml("<p>Regards,<br>Hari</p>")).querySelector("p")!;
    expect(mid.innerHTML).toBe("Regards,<br>Hari");
  });

  it("never overrides author formatting (alignment, indent) while filling defaults", () => {
    const p = parse(toEmailHtml('<p style="text-align: center; margin-left: 80px">x</p>')).querySelector("p")!;
    const style = p.getAttribute("style")!;
    expect(style).toContain("text-align:center");
    expect(style).toContain("margin-left:80px");
    expect(style).toContain("margin-bottom:10px");
  });

  it("gives list paragraphs no gap and nested lists the editor's marker styles", () => {
    const out = parse(
      toEmailHtml("<ul><li><p>Main</p><ul><li><p>Sub</p></li></ul></li></ul><ol><li><p>One</p></li></ol>")
    );
    const [outer, inner] = Array.from(out.querySelectorAll("ul"));
    expect(outer.getAttribute("style")).toContain("list-style-type:disc");
    expect(outer.getAttribute("style")).toContain("margin-bottom:10px");
    expect(inner.getAttribute("style")).toContain("list-style-type:circle");
    expect(inner.getAttribute("style")).toContain("margin-bottom:0");
    expect(out.querySelector("ol")!.getAttribute("style")).toContain("list-style-type:decimal");
    out.querySelectorAll("li > p").forEach((p) => expect(p.getAttribute("style")).toBe("margin-top:0;margin-bottom:0"));
  });

  it("styles quotes and links inline so they survive email clients", () => {
    const out = parse(toEmailHtml('<blockquote><p>Earlier</p></blockquote><p><a href="https://x.test">x</a></p>'));
    expect(out.querySelector("blockquote")!.getAttribute("style")).toContain("border-left:2px solid #cccccc");
    expect(out.querySelector("a")!.getAttribute("style")).toContain("text-decoration:underline");
  });

  it("is idempotent — re-processing a saved draft does not nest wrappers or double fillers", () => {
    const once = toEmailHtml("<p>Hi</p><p></p><p>Line<br></p>");
    expect(toEmailHtml(once)).toBe(once);
  });

  it("passes empty input through", () => {
    expect(toEmailHtml("")).toBe("");
  });
});

describe("fromEmailHtml — loading a saved draft back into the editor", () => {
  it("removes the fillers toEmailHtml added, so blank lines don't double", () => {
    const loaded = fromEmailHtml(toEmailHtml("<p>Hi</p><p></p><p>Line<br></p>"));
    const paragraphs = parse(loaded).querySelectorAll("p");
    expect(paragraphs[1].innerHTML).toBe("");
    expect(paragraphs[2].innerHTML).toBe("Line<br>");
  });

  it("leaves normal content untouched", () => {
    expect(fromEmailHtml("<p>a<br>b</p>")).toBe("<p>a<br>b</p>");
  });
});

describe("normalizeLinkUrl / isSafeLinkHref", () => {
  it.each([
    ["https://probeps.com/x", "https://probeps.com/x"],
    ["http://a.test", "http://a.test"],
    ["probeps.com/path", "https://probeps.com/path"],
    ["www.example.com", "https://www.example.com"],
    ["john@example.com", "mailto:john@example.com"],
    ["mailto:john@example.com", "mailto:john@example.com"],
    ["example.com:8080/x", "https://example.com:8080/x"],
  ])("accepts %s", (input, expected) => {
    expect(normalizeLinkUrl(input)).toBe(expected);
  });

  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    " java\tscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "file:///c:/x",
    "",
    "not a url",
  ])("rejects %j", (input) => {
    expect(normalizeLinkUrl(input)).toBeNull();
  });

  it("only accepts http(s)/mailto hrefs already in content", () => {
    expect(isSafeLinkHref("https://x.test")).toBe(true);
    expect(isSafeLinkHref("mailto:a@b.co")).toBe(true);
    expect(isSafeLinkHref("javascript:alert(1)")).toBe(false);
    expect(isSafeLinkHref("java\nscript:alert(1)")).toBe(false);
  });
});

describe("toolbar value helpers", () => {
  it("maps stored font sizes back to point labels", () => {
    expect(fontSizeToPoints("14pt")).toBe("14");
    expect(fontSizeToPoints("16px")).toBe("12");
    expect(fontSizeToPoints(null)).toBeNull();
  });

  it("matches a stored font-family stack to its option regardless of quoting", () => {
    expect(findFontFamilyOption("Arial, Helvetica, sans-serif")?.label).toBe("Arial");
    expect(findFontFamilyOption('"Times New Roman", Times, serif')?.label).toBe("Times New Roman");
    expect(findFontFamilyOption("Comic Sans MS")).toBeUndefined();
  });
});

describe("buildOutgoingBodyHtml — the body_html every email send/draft submits", () => {
  it("returns undefined for an empty editor", () => {
    expect(buildOutgoingBodyHtml("<p></p>")).toBeUndefined();
    expect(buildOutgoingBodyHtml("")).toBeUndefined();
  });

  it("sends HTML even for a plain multi-paragraph message (spacing would be lost as text)", () => {
    const out = buildOutgoingBodyHtml("<p>Hello John,</p><p>Thanks.</p>");
    expect(out).toBeDefined();
    expect(out).toContain("margin-bottom:10px");
  });

  it("keeps the signature's own formatting and turns its logo into the cid reference", () => {
    const initial = buildInitialBodyHtml({
      signatureBlockHtml: buildSignatureBlockHtml(
        {
          id: "sig-1",
          html: '<p><strong>Hari Krishna</strong><br><span style="color: #0070c0">Probe</span></p><div><img src="cid:company-signature-logo-v1" alt="Probe Practice Solutions" width="150"></div>',
        },
        {}
      ),
    });
    const out = buildOutgoingBodyHtml(`<p>Thank you.</p>${initial}`)!;
    expect(out).toContain(`cid:${COMPANY_LOGO_CONTENT_ID}`);
    expect(out).toContain('<span style="color: #0070c0">Probe</span>');
    expect(out).toContain("<strong>Hari Krishna</strong>");
  });
});
