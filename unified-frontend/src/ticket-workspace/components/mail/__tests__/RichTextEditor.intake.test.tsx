import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EditorView } from "@tiptap/pm/view";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttachmentDropArea } from "@tw/components/common/AttachmentDropArea";
import { RichTextEditor } from "@tw/components/mail/RichTextEditor";
import { fakeDataTransfer, makeFile } from "@tw/lib/__tests__/testUtils";

// Real TipTap editor inside the real drop/paste layer. This pins the
// contract the feature depends on: TipTap's own image handling is
// untouched (images stay inline), and anything TipTap does not take —
// non-image files — reaches the attachment pipeline exactly once.

const pdf = makeFile("invoice.pdf", "application/pdf");
const docx = makeFile("letter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
const png = makeFile("shot.png", "image/png");

const onFiles = vi.fn();
const onImageUpload = vi.fn().mockResolvedValue({ attachmentId: "a1", contentId: "c1" });

async function renderEditor() {
  render(
    <AttachmentDropArea onFiles={onFiles}>
      <RichTextEditor value="" onChange={vi.fn()} onImageUpload={onImageUpload} />
    </AttachmentDropArea>
  );
  return waitFor(() => {
    const el = document.querySelector(".ProseMirror");
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
}

function paste(target: Element, init: Parameters<typeof fakeDataTransfer>[0]) {
  const event = createEvent.paste(target, { clipboardData: fakeDataTransfer(init) });
  fireEvent(target, event);
  return event;
}

function drop(target: Element, files: File[]) {
  const event = createEvent.drop(target, { dataTransfer: fakeDataTransfer({ files }), clientX: 1, clientY: 1 });
  fireEvent(target, event);
  return event;
}

beforeEach(() => {
  onFiles.mockClear();
  onImageUpload.mockClear();
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
  // jsdom has no layout, so ProseMirror can't map a drop's coordinates
  // to a document position and bails out before ever calling handleDrop.
  // A real browser always resolves one.
  vi.spyOn(EditorView.prototype, "posAtCoords").mockReturnValue({ pos: 1, inside: -1 });
});

describe("image paste/drop inside the editor stays inline (existing behavior)", () => {
  it("a pasted image uploads as an inline image and is not attached", async () => {
    const editor = await renderEditor();
    const event = paste(editor, { files: [png] });
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(onImageUpload).toHaveBeenCalledWith(png));
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("a dropped image uploads as an inline image and is not attached", async () => {
    const editor = await renderEditor();
    drop(editor, [png]);
    await waitFor(() => expect(onImageUpload).toHaveBeenCalledWith(png));
    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe("non-image files in the editor become normal attachments", () => {
  it("a pasted PDF is attached and never goes through the inline-image upload", async () => {
    const editor = await renderEditor();
    paste(editor, { files: [pdf] });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(onImageUpload).not.toHaveBeenCalled();
  });

  it("a dropped PDF is attached, exactly once", async () => {
    const editor = await renderEditor();
    const event = drop(editor, [pdf]);
    expect(event.defaultPrevented).toBe(true);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    expect(onImageUpload).not.toHaveBeenCalled();
  });

  it("a mixed image + PDF paste: image inline, PDF attached", async () => {
    const editor = await renderEditor();
    paste(editor, { files: [png, pdf] });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([pdf]);
    await waitFor(() => expect(onImageUpload).toHaveBeenCalledTimes(1));
    expect(onImageUpload).toHaveBeenCalledWith(png);
  });

  it("a mixed image + DOCX drop: image inline, DOCX attached", async () => {
    const editor = await renderEditor();
    drop(editor, [png, docx]);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith([docx]);
    await waitFor(() => expect(onImageUpload).toHaveBeenCalledTimes(1));
    expect(onImageUpload).toHaveBeenCalledWith(png);
  });
});

describe("plain text keeps pasting as text", () => {
  it("a text-only paste is neither attached nor uploaded and is left to the editor", async () => {
    const editor = await renderEditor();
    paste(editor, { data: { "text/plain": "Please review this ticket." } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(onImageUpload).not.toHaveBeenCalled();
    expect(screen.queryByText("text.txt")).not.toBeInTheDocument();
  });
});
