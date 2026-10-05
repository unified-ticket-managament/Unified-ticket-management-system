import { describe, expect, it } from "vitest";

import { filterPastedStyle, sanitizePastedHtml } from "@tw/lib/clipboardPaste";

function parse(html: string): HTMLElement {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

// A trimmed-down but structurally faithful Outlook (desktop) clipboard
// payload: zero-margin MsoNormal paragraphs (one per Enter), empty
// spacer paragraphs for blank lines, mso-* noise and default fonts.
const OUTLOOK_CLIPBOARD = `<html xmlns:o="urn:schemas-microsoft-com:office:office">
<head><style>
p.MsoNormal, li.MsoNormal, div.MsoNormal
	{margin:0in;
	font-size:11.0pt;
	font-family:"Calibri",sans-serif;}
</style></head>
<body lang=EN-US>
<div class=WordSection1>
<p class=MsoNormal>Hello Team,<o:p></o:p></p>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<p class=MsoNormal>We have reviewed the claim and
identified the issue.<o:p></o:p></p>
<p class=MsoNormal><o:p>&nbsp;</o:p></p>
<p class=MsoNormal>Regards,<o:p></o:p></p>
<p class=MsoNormal><b><span style='font-size:14.0pt;color:#C00000;mso-fareast-font-family:Calibri'>Hari Krishna</span></b><o:p></o:p></p>
</div>
</body></html>`;

// Word's own Normal style has "space after", so each <p> really is a
// paragraph; its list items are mso-list paragraphs with literal
// bullet/number glyphs.
const WORD_CLIPBOARD = `<html xmlns:w="urn:schemas-microsoft-com:office:word">
<head><style>
p.MsoNormal {margin-top:0in;margin-right:0in;margin-bottom:8.0pt;margin-left:0in;line-height:107%;font-size:11.0pt;}
</style></head><body>
<p class=MsoNormal>Please complete the following:</p>
<p class=MsoListParagraphCxSpFirst style='text-indent:-.25in;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='mso-list:Ignore'>1.<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp; </span></span><![endif]>Verify the corrected claim.</p>
<p class=MsoListParagraphCxSpMiddle style='margin-left:1.0in;text-indent:-.25in;mso-list:l0 level2 lfo1'><![if !supportLists]><span style='mso-list:Ignore'>a.<span>&nbsp; </span></span><![endif]>Check the CPT codes.</p>
<p class=MsoListParagraphCxSpLast style='text-indent:-.25in;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='mso-list:Ignore'>2.<span>&nbsp; </span></span><![endif]>Update the patient information.</p>
<p class=MsoNormal>Thanks</p>
<p class=MsoListParagraph style='text-indent:-.25in;mso-list:l1 level1 lfo2'><![if !supportLists]><span style='font-family:Symbol;mso-list:Ignore'>·<span>&nbsp; </span></span><![endif]>Bullet point</p>
</body></html>`;

describe("pasting from Outlook", () => {
  it("keeps line/paragraph structure: lines join with <br>, blank lines become paragraph breaks", () => {
    const out = parse(sanitizePastedHtml(OUTLOOK_CLIPBOARD));
    const paragraphs = Array.from(out.querySelectorAll("p"));
    expect(paragraphs).toHaveLength(3);
    expect(paragraphs[0].textContent).toBe("Hello Team,");
    // Source-code line wrapping is not content — it's whitespace.
    expect(paragraphs[1].textContent?.replace(/\s+/g, " ")).toBe("We have reviewed the claim and identified the issue.");
    expect(paragraphs[2].innerHTML).toContain("Regards,<br>");
    expect(paragraphs[2].textContent).toContain("Hari Krishna");
  });

  it("keeps useful formatting but drops mso-* noise and default fonts", () => {
    const html = sanitizePastedHtml(OUTLOOK_CLIPBOARD);
    expect(html).not.toMatch(/mso-|MsoNormal|o:p|<style/i);
    expect(html).toContain("<b>");
    const span = parse(html).querySelector("span")!;
    expect(span.getAttribute("style")).toBe("font-size: 14pt; color: #c00000");
  });
});

describe("pasting from Word", () => {
  it("rebuilds real nested ordered/bulleted lists from mso-list paragraphs", () => {
    const out = parse(sanitizePastedHtml(WORD_CLIPBOARD));
    const lists = out.querySelectorAll(":scope > ol, :scope > ul");
    expect(lists).toHaveLength(2);
    const [numbered, bulleted] = Array.from(lists);
    expect(numbered.tagName).toBe("OL");
    expect(bulleted.tagName).toBe("UL");

    const topItems = numbered.querySelectorAll(":scope > li");
    expect(topItems).toHaveLength(2);
    expect(topItems[0].textContent).toContain("Verify the corrected claim.");
    expect(topItems[0].querySelector("ol > li")?.textContent).toContain("Check the CPT codes.");
    expect(topItems[1].textContent).toContain("Update the patient information.");
    // The literal "1." / "·" glyphs are gone — the list renders them.
    expect(out.textContent).not.toMatch(/1\.\s|·/);
  });

  it("does not merge real Word paragraphs (Word's Normal style has a paragraph gap)", () => {
    const out = parse(sanitizePastedHtml(WORD_CLIPBOARD));
    const topParagraphs = Array.from(out.children).filter((el) => el.tagName === "P");
    expect(topParagraphs.map((p) => p.textContent)).toEqual(["Please complete the following:", "Thanks"]);
  });
});

describe("pasting from the web / plain HTML", () => {
  it("removes empty spacer blocks that would otherwise double the paragraph gap", () => {
    const out = parse(sanitizePastedHtml("<div>One</div><div><br></div><div>Two</div><p>&nbsp;</p><p>Three</p>"));
    expect(out.textContent).toBe("OneTwoThree");
    expect(out.querySelectorAll("div, p")).toHaveLength(3);
  });

  it("drops huge/tiny fonts and unknown font stacks, keeps sane ones", () => {
    const html = sanitizePastedHtml(
      '<p><span style="font-size:72px">huge</span> <span style="font-size:16px;font-family:-apple-system">ok</span></p>'
    );
    const spans = parse(html).querySelectorAll("span");
    expect(spans[0]?.getAttribute("style") ?? null).toBeNull();
    expect(spans[1].getAttribute("style")).toBe("font-size: 12pt");
  });

  it("converts legacy <font> tags to styled spans", () => {
    const html = sanitizePastedHtml('<p><font color="#0070c0" face="Arial" size="4">Blue</font></p>');
    expect(html).toContain('style="color: #0070c0; font-family: Arial, Helvetica, sans-serif; font-size: 14pt"');
  });

  it("preserves bold/italic/underline/lists/links", () => {
    const html = sanitizePastedHtml(
      '<p><b>b</b> <i>i</i> <u>u</u> <a href="https://x.test">link</a></p><ul><li>one</li></ul>'
    );
    expect(html).toBe('<p><b>b</b> <i>i</i> <u>u</u> <a href="https://x.test">link</a></p><ul><li>one</li></ul>');
  });
});

describe("paste security", () => {
  it("strips scripts, event handlers, javascript: links and unsafe CSS", () => {
    const html = sanitizePastedHtml(
      '<p onclick="alert(1)">x<script>alert(1)</script><img src="x" onerror="alert(1)">' +
        '<a href="javascript:alert(1)">bad</a>' +
        '<span style="background:url(javascript:alert(1));color:expression(alert(1))">y</span></p>' +
        "<iframe src=\"https://evil.test\"></iframe><style>p{color:red}</style>"
    );
    expect(html).not.toMatch(/onclick|onerror|<script|javascript:|expression|url\(|<iframe|<style/i);
  });

  it("filterPastedStyle keeps only formatting the toolbar can represent", () => {
    expect(
      filterPastedStyle(
        "margin:0in;line-height:107%;mso-bidi-font-family:Arial;color:windowtext;text-align:center;margin-left:.5in",
        "P"
      )
    ).toBe("text-align: center; margin-left: 48px");
    expect(filterPastedStyle("background:yellow;mso-highlight:yellow", "SPAN")).toBe("background-color: yellow");
    expect(filterPastedStyle("position:absolute;z-index:9", "SPAN")).toBeNull();
  });
});
