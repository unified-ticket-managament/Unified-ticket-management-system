import { act, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmailEditorToolbar } from "@tw/components/mail/EmailEditorToolbar";
import { createRichTextExtensions } from "@tw/components/mail/RichTextEditor";
import { createPasteHandler, parsePlainTextClipboard } from "@tw/lib/clipboardPaste";
import { fakeDataTransfer } from "@tw/lib/__tests__/testUtils";
import { buildForwardHtml, buildInitialBodyHtml, buildOutgoingBodyHtml } from "@tw/lib/richText";
import { buildSignatureBlockHtml } from "@tw/lib/signatures";

// Headless TipTap editor with EXACTLY the production extension set and
// paste wiring (createRichTextExtensions + the same editorProps the
// RichTextEditor component installs), so every assertion below is
// about the real schema/commands every composer uses — Compose, Reply,
// Reply All, Forward and Ticket Reply all render this one editor.

const editors: Editor[] = [];

function makeEditor(content = "<p></p>") {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: createRichTextExtensions(),
    content,
    editorProps: {
      handlePaste: createPasteHandler({ onImageFile: vi.fn() }),
      clipboardTextParser: parsePlainTextClipboard,
    },
  });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  editors.splice(0).forEach((editor) => editor.destroy());
});

// Types at the current cursor (like a user would). The first call on a
// fresh editor starts at the end of the (empty) document.
function typeAtEnd(editor: Editor, text: string) {
  if (!editor.isFocused && editor.state.selection.from === 0) editor.commands.focus("end");
  editor.commands.insertContent(text);
}

// A real keydown on the editor DOM — the same path a user's keypress
// takes (TipTap's keyboardShortcut command nests the handler inside its
// own transaction, which misrepresents undo/redo history).
function press(editor: Editor, shortcut: string) {
  const parts = shortcut.split("-");
  const key = parts[parts.length - 1];
  const shift = parts.includes("Shift");
  const named = key.length > 1;
  fireEvent.keyDown(editor.view.dom, {
    key: !named && shift ? key.toUpperCase() : key,
    keyCode: key === "Enter" ? 13 : key.toUpperCase().charCodeAt(0),
    ctrlKey: parts.includes("Mod"),
    shiftKey: shift,
  });
}

// Selects the first occurrence of `text` in the document.
function select(editor: Editor, text: string) {
  let from = -1;
  editor.state.doc.descendants((node, pos) => {
    if (from !== -1 || !node.isText) return;
    const index = node.text!.indexOf(text);
    if (index !== -1) from = pos + index;
  });
  if (from === -1) throw new Error(`"${text}" not found`);
  editor.commands.setTextSelection({ from, to: from + text.length });
}

function pasteInto(editor: Editor, data: Record<string, string>) {
  const target = editor.view.dom;
  const event = createEvent.paste(target, { clipboardData: fakeDataTransfer({ data }) });
  fireEvent(target, event);
}

describe("paragraphs and line breaks", () => {
  it("Enter creates a new <p>, never <br><br>", () => {
    const editor = makeEditor();
    typeAtEnd(editor, "Hello John,");
    press(editor, "Enter");
    typeAtEnd(editor, "Thank you for your email.");
    expect(editor.getHTML()).toBe("<p>Hello John,</p><p>Thank you for your email.</p>");
  });

  it("Shift+Enter creates a soft line break inside the same paragraph", () => {
    const editor = makeEditor();
    typeAtEnd(editor, "Regards,");
    press(editor, "Shift-Enter");
    typeAtEnd(editor, "Hari");
    expect(editor.getHTML()).toBe("<p>Regards,<br>Hari</p>");
  });

  it("long text stays one paragraph — wrapping is visual, never stored", () => {
    const editor = makeEditor();
    const sentence =
      "We have received your request and reviewed the information provided by your team. We will update you once the corrected claim has been processed.";
    typeAtEnd(editor, sentence);
    expect(editor.getHTML()).toBe(`<p>${sentence}</p>`);
  });

  it("a single Enter between paragraphs produces no empty paragraph", () => {
    const editor = makeEditor();
    typeAtEnd(editor, "One");
    press(editor, "Enter");
    typeAtEnd(editor, "Two");
    press(editor, "Enter");
    typeAtEnd(editor, "Three");
    expect(editor.getHTML()).not.toContain("<p></p>");
    expect(editor.getHTML().match(/<p>/g)).toHaveLength(3);
  });

  it("the sent HTML uses one controlled gap per paragraph (no doubled spacing)", () => {
    const editor = makeEditor();
    typeAtEnd(editor, "One");
    press(editor, "Enter");
    typeAtEnd(editor, "Two");
    const sent = buildOutgoingBodyHtml(editor.getHTML())!;
    expect(sent.match(/margin-bottom:10px/g)).toHaveLength(2);
    expect(sent).not.toContain("<br");
  });
});

describe("character formatting", () => {
  it.each([
    ["Mod-b", "<strong>"],
    ["Mod-i", "<em>"],
    ["Mod-u", "<u>"],
    ["Mod-Shift-s", "<s>"],
  ])("%s applies %s to the selection only", (shortcut, tag) => {
    const editor = makeEditor("<p>plain styled plain</p>");
    select(editor, "styled");
    press(editor, shortcut);
    const html = editor.getHTML();
    expect(html).toContain(`${tag}styled</`);
    expect(html.indexOf(tag)).toBeGreaterThan(html.indexOf("plain"));
  });

  it("font family applies only to the selected text", () => {
    const editor = makeEditor("<p>Hello world</p>");
    select(editor, "world");
    editor.chain().setFontFamily("Arial, Helvetica, sans-serif").run();
    expect(editor.getHTML()).toBe('<p>Hello <span style="font-family: Arial, Helvetica, sans-serif;">world</span></p>');
  });

  it("font size, color and highlight become one inline-styled span", () => {
    const editor = makeEditor("<p>Hello world</p>");
    select(editor, "world");
    editor.chain().setFontSize("16pt").setColor("#ff0000").setBackgroundColor("#ffff00").run();
    const span = new DOMParser().parseFromString(editor.getHTML(), "text/html").querySelector("span")!;
    expect(span.textContent).toBe("world");
    expect(span.style.fontSize).toBe("16pt");
    expect(span.style.color).toBe("rgb(255, 0, 0)");
    expect(span.style.backgroundColor).toBe("rgb(255, 255, 0)");
  });

  it("font, size and color picked before typing persist for the new text", () => {
    const editor = makeEditor("<p>Start </p>");
    editor.chain().focus("end").setFontFamily("Arial, Helvetica, sans-serif").setFontSize("14pt").setColor("#0070c0").run();
    editor.commands.insertContent("typed");
    editor.commands.insertContent(" more");
    const span = new DOMParser().parseFromString(editor.getHTML(), "text/html").querySelector("span")!;
    expect(span.textContent).toBe("typed more");
    expect(span.getAttribute("style")).toContain("font-size: 14pt");
    expect(span.getAttribute("style")).toContain("font-family: Arial");
  });

  it("Clear formatting removes formatting but keeps the text and its link", () => {
    const editor = makeEditor(
      '<p style="text-align: center">x <strong><em><span style="color: #ff0000; font-size: 18pt">bold red</span></em></strong> <a href="https://x.test">link</a></p>'
    );
    editor.commands.selectAll();
    render(<EmailEditorToolbar editor={editor} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear formatting" }));
    expect(editor.getHTML()).toBe(
      '<p>x bold red <a target="_blank" rel="noopener noreferrer nofollow" href="https://x.test">link</a></p>'
    );
  });
});

describe("paragraph formatting", () => {
  it.each(["center", "right", "justify"] as const)("align %s sets text-align on the paragraph", (alignment) => {
    const editor = makeEditor("<p>Text</p>");
    editor.commands.setTextAlign(alignment);
    expect(editor.getHTML()).toBe(`<p style="text-align: ${alignment};">Text</p>`);
  });

  it("align left removes the alignment (left is the default)", () => {
    const editor = makeEditor('<p style="text-align: center">Text</p>');
    editor.commands.unsetTextAlign();
    expect(editor.getHTML()).toBe("<p>Text</p>");
  });

  it("increase/decrease indent steps margin-left — no spaces, no tabs", () => {
    const editor = makeEditor("<p>Text</p>");
    editor.commands.indent();
    editor.commands.indent();
    expect(editor.getHTML()).toBe('<p style="margin-left: 80px;">Text</p>');
    editor.commands.outdent();
    expect(editor.getHTML()).toBe('<p style="margin-left: 40px;">Text</p>');
    editor.commands.outdent();
    expect(editor.getHTML()).toBe("<p>Text</p>");
    expect(editor.can().outdent()).toBe(false);
    expect(editor.getHTML()).not.toMatch(/&nbsp;|\t/);
  });

  it("bulleted and numbered lists are real <ul>/<ol>", () => {
    const editor = makeEditor("<p>First</p>");
    editor.commands.toggleBulletList();
    expect(editor.getHTML()).toBe("<ul><li><p>First</p></li></ul><p></p>");
    editor.commands.toggleOrderedList();
    expect(editor.getHTML()).toBe("<ol><li><p>First</p></li></ol><p></p>");
  });

  it("Enter continues a list and Enter on an empty item exits it", () => {
    const editor = makeEditor("<ol><li><p>First</p></li></ol>");
    select(editor, "First");
    editor.commands.focus(editor.state.selection.to);
    press(editor, "Enter");
    typeAtEnd(editor, "Second");
    press(editor, "Enter");
    press(editor, "Enter");
    typeAtEnd(editor, "After");
    // (The trailing empty <p> is TipTap's TrailingNode — never sent, see
    // toEmailHtml.)
    expect(editor.getHTML()).toBe("<ol><li><p>First</p></li><li><p>Second</p></li></ol><p>After</p><p></p>");
  });

  it("increase indent inside a list nests the item (a real nested list)", () => {
    const editor = makeEditor("<ul><li><p>Main point</p></li><li><p>Sub point</p></li></ul>");
    select(editor, "Sub point");
    editor.commands.indent();
    expect(editor.getHTML()).toBe("<ul><li><p>Main point</p><ul><li><p>Sub point</p></li></ul></li></ul><p></p>");
    editor.commands.outdent();
    expect(editor.getHTML()).toBe("<ul><li><p>Main point</p></li><li><p>Sub point</p></li></ul><p></p>");
  });

  it("blockquote wraps the paragraph", () => {
    const editor = makeEditor("<p>Quoted</p>");
    editor.commands.toggleBlockquote();
    expect(editor.getHTML()).toBe("<blockquote><p>Quoted</p></blockquote><p></p>");
  });
});

describe("links", () => {
  it("Insert Link on selected text, then Remove Link", () => {
    const editor = makeEditor("<p>Visit our site</p>");
    select(editor, "our site");
    editor.chain().setLink({ href: "https://probeps.com" }).run();
    expect(editor.getHTML()).toContain('href="https://probeps.com"');
    editor.chain().extendMarkRange("link").unsetLink().run();
    expect(editor.getHTML()).toBe("<p>Visit our site</p>");
  });

  it("refuses javascript: links (command and loaded content)", () => {
    const editor = makeEditor('<p><a href="javascript:alert(1)">bad</a> text</p>');
    expect(editor.getHTML()).not.toContain("javascript:");
    select(editor, "text");
    editor.chain().setLink({ href: "javascript:alert(1)" }).run();
    expect(editor.getHTML()).not.toContain("javascript:");
  });

  it("the toolbar's link dialog validates and normalizes the URL", () => {
    const editor = makeEditor("<p>Visit us</p>");
    select(editor, "us");
    render(<EmailEditorToolbar editor={editor} />);
    fireEvent.click(screen.getByRole("button", { name: "Insert link" }));
    const input = screen.getByLabelText("Link URL");
    fireEvent.change(input, { target: { value: "javascript:alert(1)" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(editor.getHTML()).not.toContain("href");
    fireEvent.change(input, { target: { value: "probeps.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(editor.getHTML()).toContain('href="https://probeps.com"');
  });
});

describe("undo / redo", () => {
  it("uses the editor's native history (Mod-z / Mod-y)", () => {
    const editor = makeEditor("<p>Text</p>");
    select(editor, "Text");
    press(editor, "Mod-b");
    expect(editor.getHTML()).toBe("<p><strong>Text</strong></p>");
    press(editor, "Mod-z");
    expect(editor.getHTML()).toBe("<p>Text</p>");
    press(editor, "Mod-y");
    expect(editor.getHTML()).toBe("<p><strong>Text</strong></p>");
  });
});

describe("paste", () => {
  it("plain text: blank lines separate paragraphs, single newlines are line breaks", () => {
    const editor = makeEditor();
    pasteInto(editor, { "text/plain": "Hello Team,\n\nWe reviewed the claim.\nPlease confirm.\n\n\nRegards,\nHari" });
    expect(editor.getHTML()).toBe(
      "<p>Hello Team,</p><p>We reviewed the claim.<br>Please confirm.</p><p>Regards,<br>Hari</p>"
    );
  });

  it("Outlook-like HTML: no stray blank paragraphs, formatting kept", () => {
    const editor = makeEditor();
    pasteInto(editor, {
      "text/html":
        '<html><head><style>p.MsoNormal {margin:0in;}</style></head><body>\n' +
        "<p class=MsoNormal>Hello,<o:p></o:p></p>\n<p class=MsoNormal><o:p>&nbsp;</o:p></p>\n" +
        "<p class=MsoNormal><b>Important</b> update<o:p></o:p></p>\n</body></html>",
      "text/plain": "Hello,\n\nImportant update",
    });
    expect(editor.getHTML()).toBe("<p>Hello,</p><p><strong>Important</strong> update</p>");
  });

  it("copying within the editor round-trips formatting", () => {
    const editor = makeEditor();
    pasteInto(editor, {
      "text/html":
        '<p>Before</p><p style="text-align: center"><span style="color: #ff0000; font-size: 14pt">Red</span></p><p>After</p>',
    });
    expect(editor.getHTML()).toBe(
      '<p>Before</p><p style="text-align: center;"><span style="font-size: 14pt; color: rgb(255, 0, 0);">Red</span></p><p>After</p>'
    );
  });
});

describe("toolbar reflects the current cursor/selection", () => {
  it("tracks bold, alignment, list, font size and color as the cursor moves", () => {
    const editor = makeEditor(
      '<p style="text-align: center"><strong>bold</strong> <span style="font-size: 16pt; color: #ff0000">big</span></p><ul><li><p>item</p></li></ul>'
    );
    render(<EmailEditorToolbar editor={editor} />);
    const bold = screen.getByRole("button", { name: "Bold" });
    const center = screen.getByRole("button", { name: "Center" });
    const bullets = screen.getByRole("button", { name: "Bulleted list" });
    const size = screen.getByLabelText("Font size") as HTMLSelectElement;

    act(() => {
      select(editor, "old");
    });
    expect(bold).toHaveAttribute("aria-pressed", "true");
    expect(center).toHaveAttribute("aria-pressed", "true");
    expect(bullets).toHaveAttribute("aria-pressed", "false");

    act(() => {
      select(editor, "ig");
    });
    expect(bold).toHaveAttribute("aria-pressed", "false");
    expect(size.value).toBe("16");
    expect(screen.getByTestId("font-color-indicator")).toHaveStyle({ backgroundColor: "#ff0000" });

    act(() => {
      select(editor, "item");
    });
    expect(bullets).toHaveAttribute("aria-pressed", "true");
    expect(center).toHaveAttribute("aria-pressed", "false");
    expect(size.value).toBe("11");
  });

  it("toolbar font/size selects apply to the selection", () => {
    const editor = makeEditor("<p>Hello world</p>");
    render(<EmailEditorToolbar editor={editor} />);
    act(() => select(editor, "world"));
    fireEvent.change(screen.getByLabelText("Font"), { target: { value: "Georgia, serif" } });
    fireEvent.change(screen.getByLabelText("Font size"), { target: { value: "20" } });
    expect(editor.getHTML()).toBe('<p>Hello <span style="font-family: Georgia, serif; font-size: 20pt;">world</span></p>');
  });

  it("highlight palette applies a background color", () => {
    const editor = makeEditor("<p>Hello world</p>");
    render(<EmailEditorToolbar editor={editor} />);
    act(() => select(editor, "world"));
    fireEvent.click(screen.getByRole("button", { name: "Highlight color" }));
    fireEvent.click(screen.getByRole("button", { name: "Highlight color: Yellow" }));
    expect(editor.getHTML()).toBe('<p>Hello <span style="background-color: rgb(255, 255, 0);">world</span></p>');
  });
});

describe("signature and quoted content stay separate", () => {
  const SIGNATURE =
    '<p><strong>Hari Krishna</strong><br><span style="color: #0070c0;">Probe Practice Solutions</span><br><a href="https://probeps.com">probeps.com</a></p>';

  it("formatting the new text never touches the signature or its logo", () => {
    // A migrated default signature: the user's text plus the company
    // logo, now carried as ordinary signature content.
    const block = buildSignatureBlockHtml({ id: "sig-1", html: SIGNATURE + '<div><img src="cid:company-signature-logo-v1" alt="Probe Practice Solutions" width="150"></div>' }, {});
    const editor = makeEditor(buildInitialBodyHtml({ signatureBlockHtml: block }));
    const signatureBefore = editor.getHTML().slice("<p></p>".length);
    editor.commands.focus("start");
    editor.chain().setFontSize("18pt").setColor("#ff0000").insertContent("Thank you for the update.").run();
    const html = editor.getHTML();
    // The managed signature block (a block node) gets TipTap's usual
    // trailing empty paragraph after it — dropped again by toEmailHtml.
    const withoutTrailing = (value: string) => value.replace(/(<p><\/p>)+$/, "");
    expect(withoutTrailing(html).endsWith(withoutTrailing(signatureBefore))).toBe(true);
    expect(html).toContain('<div data-utms-signature="sig-1">');
    expect(html).toContain('<img src="/probe-practice-solutions-logo.jpg" alt="Probe Practice Solutions" width="150">');
    expect(html).toContain('<span style="color: rgb(0, 112, 192);">Probe Practice Solutions</span>');

    const sent = buildOutgoingBodyHtml(html)!;
    expect(sent).toContain('src="cid:company-signature-logo-v1"');
    expect(sent).toContain('href="https://probeps.com"');
  });

  it("forwarded content keeps its own formatting when the new text is formatted", () => {
    const forward = buildForwardHtml({
      fromLabel: "Client <c@x.test>",
      dateLabel: "Mon",
      subject: "Claim",
      body: "",
      bodyHtml: '<p>Original <span style="color: #00b050;">green</span> text</p>',
    });
    const editor = makeEditor(forward);
    editor.commands.focus("start");
    editor.chain().toggleBold().insertContent("FYI").run();
    const html = editor.getHTML();
    expect(html.startsWith("<p><strong>FYI</strong></p>")).toBe(true);
    expect(html).toContain(
      '<blockquote><p>Original <span style="color: rgb(0, 176, 80);">green</span> text</p></blockquote>'
    );
  });
});

// Spec item 39 — the end-to-end visual test message. Builds the message
// with the same commands the toolbar runs, then checks the HTML that is
// actually submitted as body_html (the backend half of this pipeline —
// sanitize_outbound_html + Graph — is pinned against this same output
// in unified-backend/tests/test_email_formatting_pipeline.py).
describe("visual test message: editor HTML -> sent HTML", () => {
  it("keeps every formatting choice in email-safe inline form", () => {
    const editor = makeEditor();
    typeAtEnd(editor, "Hello Team,");
    press(editor, "Enter");
    typeAtEnd(editor, "We have reviewed the claim and identified the issue.");
    press(editor, "Enter");
    typeAtEnd(editor, "Please complete the following:");
    press(editor, "Enter");
    editor.commands.toggleOrderedList();
    typeAtEnd(editor, "Verify the corrected claim.");
    press(editor, "Enter");
    typeAtEnd(editor, "Update the patient information.");
    press(editor, "Enter");
    typeAtEnd(editor, "Confirm the revised amount.");
    press(editor, "Enter");
    press(editor, "Enter");
    typeAtEnd(editor, "Regards,");
    press(editor, "Shift-Enter");
    typeAtEnd(editor, "Hari Krishna");

    select(editor, "Hello Team,");
    editor.chain().toggleBold().run();
    select(editor, "identified the issue");
    editor.chain().toggleItalic().setColor("#c00000").run();
    select(editor, "Please complete the following:");
    editor.chain().setFontSize("14pt").indent().run();
    select(editor, "Confirm the revised amount.");
    editor.chain().toggleBold().run();
    select(editor, "Hari Krishna");
    editor.chain().setFontFamily("Arial, Helvetica, sans-serif").setTextAlign("right").run();

    const editorHtml = editor.getHTML();
    expect(editorHtml).toBe(
      "<p><strong>Hello Team,</strong></p>" +
        '<p>We have reviewed the claim and <span style="color: rgb(192, 0, 0);"><em>identified the issue</em></span>.</p>' +
        '<p style="margin-left: 40px;"><span style="font-size: 14pt;">Please complete the following:</span></p>' +
        "<ol><li><p>Verify the corrected claim.</p></li><li><p>Update the patient information.</p></li>" +
        "<li><p><strong>Confirm the revised amount.</strong></p></li></ol>" +
        '<p style="text-align: right;">Regards,<br><span style="font-family: Arial, Helvetica, sans-serif;">Hari Krishna</span></p>' +
        "<p></p>"
    );

    expect(buildOutgoingBodyHtml(editorHtml)).toBe(
      "<div data-utms-email-body=\"\" style=\"font-family:'Times New Roman', Times, serif;font-size:11pt;line-height:1.35;color:#000000\">" +
        '<p style="margin-top:0;margin-bottom:10px"><strong>Hello Team,</strong></p>' +
        '<p style="margin-top:0;margin-bottom:10px">We have reviewed the claim and <span style="color: rgb(192, 0, 0);"><em>identified the issue</em></span>.</p>' +
        '<p style="margin-left:40px;margin-top:0;margin-bottom:10px"><span style="font-size: 14pt;">Please complete the following:</span></p>' +
        '<ol style="margin-top:0;margin-bottom:10px;list-style-type:decimal">' +
        '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0">Verify the corrected claim.</p></li>' +
        '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0">Update the patient information.</p></li>' +
        '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0"><strong>Confirm the revised amount.</strong></p></li></ol>' +
        '<p style="text-align:right;margin-top:0;margin-bottom:10px">Regards,<br><span style="font-family: Arial, Helvetica, sans-serif;">Hari Krishna</span></p>' +
        "</div>"
    );
  });
});
