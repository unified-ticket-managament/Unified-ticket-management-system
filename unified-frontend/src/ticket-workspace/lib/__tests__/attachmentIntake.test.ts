import { describe, expect, it } from "vitest";

import { MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES } from "@tw/lib/attachmentMeta";
import {
  classifyDrop,
  classifyPaste,
  getClipboardFiles,
  isFileDrag,
  isImageOnlyDrag,
  mergeAttachmentFiles,
} from "@tw/lib/attachmentIntake";
import { fakeDataTransfer, makeFile } from "./testUtils";

describe("mergeAttachmentFiles", () => {
  it("accepts every representative document type", () => {
    const names = ["claim.pdf", "letter.docx", "sheet.xlsx", "data.csv", "notes.txt", "bundle.zip"];
    const { accepted, errors } = mergeAttachmentFiles([], names.map((n) => makeFile(n)));
    expect(accepted.map((f) => f.name)).toEqual(names);
    expect(errors).toEqual([]);
  });

  it("rejects unsupported and oversized files with the existing messages, keeping valid ones", () => {
    const { accepted, errors } = mergeAttachmentFiles(
      [],
      [makeFile("ok.pdf"), makeFile("bad.exe"), makeFile("huge.pdf", "", MAX_ATTACHMENT_SIZE_BYTES + 1)]
    );
    expect(accepted.map((f) => f.name)).toEqual(["ok.pdf"]);
    expect(errors).toHaveLength(2);
    expect(errors[0]).toContain("unsupported file type");
    expect(errors[1]).toContain("size limit");
  });

  it("enforces the file-count cap including already-attached files", () => {
    const existing = Array.from({ length: MAX_ATTACHMENT_FILES - 1 }, (_, i) => makeFile(`e${i}.pdf`));
    const { accepted, errors } = mergeAttachmentFiles(existing, [makeFile("a.pdf"), makeFile("b.pdf")]);
    expect(accepted).toHaveLength(MAX_ATTACHMENT_FILES);
    expect(errors[0]).toContain(`Only ${MAX_ATTACHMENT_FILES} files`);
  });

  it("silently drops a duplicate of an already-attached file (existing dedupe)", () => {
    const original = makeFile("a.pdf");
    const duplicate = new File(["x"], "a.pdf", { lastModified: original.lastModified });
    Object.defineProperty(duplicate, "size", { value: original.size });
    const { accepted, errors } = mergeAttachmentFiles([original], [duplicate]);
    expect(accepted).toEqual([original]);
    expect(errors).toEqual([]);
  });

  it("respects a lowered maxFiles (Forward's remaining slots)", () => {
    const { accepted, errors } = mergeAttachmentFiles([], [makeFile("a.pdf"), makeFile("b.pdf")], 1);
    expect(accepted).toHaveLength(1);
    expect(errors[0]).toContain("Only 1 files");
  });

  it("gives every input method the same verdict for the same file", () => {
    const oversize = makeFile("big.pdf", "", MAX_ATTACHMENT_SIZE_BYTES + 1);
    const viaPicker = mergeAttachmentFiles([], [oversize]);
    const viaPaste = mergeAttachmentFiles([], classifyPaste(fakeDataTransfer({ files: [oversize] }), false).attach);
    const viaDrop = mergeAttachmentFiles([], classifyDrop(fakeDataTransfer({ files: [oversize] }), false).attach);
    expect(viaPaste).toEqual(viaPicker);
    expect(viaDrop).toEqual(viaPicker);
  });
});

describe("getClipboardFiles", () => {
  it("returns files from clipboardData.files", () => {
    const pdf = makeFile("a.pdf", "application/pdf");
    expect(getClipboardFiles(fakeDataTransfer({ files: [pdf] }))).toEqual([pdf]);
  });

  it("falls back to items when files is empty, without double-collecting", () => {
    const png = makeFile("shot.png", "image/png");
    const dt = fakeDataTransfer({ itemFiles: [png] });
    expect(getClipboardFiles(dt)).toEqual([png]);
  });

  it("names an unnamed pasted blob so validation can judge its extension", () => {
    const blob = new File(["x"], "", { type: "image/png" });
    const [named] = getClipboardFiles(fakeDataTransfer({ files: [blob] }));
    expect(named.name).toBe("pasted-file.png");
  });

  it("returns nothing for a text-only clipboard", () => {
    expect(getClipboardFiles(fakeDataTransfer({ data: { "text/plain": "hello" } }))).toEqual([]);
    expect(getClipboardFiles(null)).toEqual([]);
  });
});

describe("classifyPaste", () => {
  const pdf = makeFile("a.pdf", "application/pdf");
  const docx = makeFile("b.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  const png = makeFile("shot.png", "image/png");

  it.each([
    ["PDF", pdf],
    ["DOCX", docx],
    ["XLSX", makeFile("c.xlsx")],
    ["CSV", makeFile("d.csv", "text/csv")],
    ["TXT", makeFile("e.txt", "text/plain")],
    ["ZIP", makeFile("f.zip", "application/zip")],
  ])("a pasted %s becomes an attachment, inside or outside the editor", (_label, file) => {
    for (const inEditor of [true, false]) {
      const result = classifyPaste(fakeDataTransfer({ files: [file] }), inEditor);
      expect(result.attach).toEqual([file]);
      expect(result.consumed).toBe(true);
    }
  });

  it("leaves a pasted image inside the editor to TipTap (inline image)", () => {
    const result = classifyPaste(fakeDataTransfer({ files: [png] }), true);
    expect(result).toEqual({ attach: [], consumed: false });
  });

  it("turns a pasted image outside the editor into an attachment", () => {
    const result = classifyPaste(fakeDataTransfer({ files: [png] }), false);
    expect(result).toEqual({ attach: [png], consumed: true });
  });

  it("splits a mixed image + PDF paste inside the editor: PDF attached, image left to TipTap", () => {
    const result = classifyPaste(fakeDataTransfer({ files: [png, pdf] }), true);
    expect(result.attach).toEqual([pdf]);
    expect(result.consumed).toBe(false);
  });

  it("attaches both for a mixed paste outside the editor", () => {
    const result = classifyPaste(fakeDataTransfer({ files: [png, pdf] }), false);
    expect(result.attach).toEqual(expect.arrayContaining([png, pdf]));
    expect(result.consumed).toBe(true);
  });

  it("never touches a plain-text paste", () => {
    for (const inEditor of [true, false]) {
      const result = classifyPaste(fakeDataTransfer({ data: { "text/plain": "Please review this ticket." } }), inEditor);
      expect(result).toEqual({ attach: [], consumed: false });
    }
  });

  it("never touches an HTML-only paste", () => {
    const result = classifyPaste(fakeDataTransfer({ data: { "text/html": "<table><tr><td>1</td></tr></table>" } }), true);
    expect(result).toEqual({ attach: [], consumed: false });
  });

  it("treats an Office text + flattened-bitmap copy as text outside the editor", () => {
    const dt = fakeDataTransfer({
      files: [png],
      data: { "text/plain": "A1\tB1", "text/html": "<table></table>" },
    });
    expect(classifyPaste(dt, false)).toEqual({ attach: [], consumed: false });
  });

  it("ignores unsupported clipboard data (no files)", () => {
    expect(classifyPaste(fakeDataTransfer({ types: ["application/x-custom"] }), false)).toEqual({
      attach: [],
      consumed: false,
    });
  });
});

describe("classifyDrop", () => {
  const pdf = makeFile("a.pdf", "application/pdf");
  const png = makeFile("shot.png", "image/png");

  it("ignores drags that carry no files (text/link drags)", () => {
    const dt = fakeDataTransfer({ types: ["text/plain"], data: { "text/plain": "selected text" } });
    expect(isFileDrag(dt)).toBe(false);
    expect(classifyDrop(dt, false)).toEqual({ attach: [], consumed: false });
    expect(classifyDrop(dt, true)).toEqual({ attach: [], consumed: false });
  });

  it("outside the editor every file is an attachment, images included", () => {
    expect(classifyDrop(fakeDataTransfer({ files: [pdf, png] }), false)).toEqual({
      attach: [pdf, png],
      consumed: true,
    });
  });

  it("inside the editor an image is left to TipTap", () => {
    expect(classifyDrop(fakeDataTransfer({ files: [png] }), true)).toEqual({ attach: [], consumed: false });
  });

  it("inside the editor a non-image file is an attachment and fully consumed", () => {
    expect(classifyDrop(fakeDataTransfer({ files: [pdf] }), true)).toEqual({ attach: [pdf], consumed: true });
  });

  it("inside the editor a mixed drop splits: PDF attached, image left to TipTap", () => {
    expect(classifyDrop(fakeDataTransfer({ files: [pdf, png] }), true)).toEqual({ attach: [pdf], consumed: false });
  });
});

describe("isImageOnlyDrag", () => {
  it("is true only when every dragged item is an image file", () => {
    expect(isImageOnlyDrag(fakeDataTransfer({ files: [makeFile("a.png", "image/png")] }))).toBe(true);
    expect(
      isImageOnlyDrag(fakeDataTransfer({ files: [makeFile("a.png", "image/png"), makeFile("b.pdf", "application/pdf")] }))
    ).toBe(false);
    expect(isImageOnlyDrag(fakeDataTransfer({}))).toBe(false);
  });
});
