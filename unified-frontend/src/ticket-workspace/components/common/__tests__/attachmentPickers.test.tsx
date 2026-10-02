import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { FileDropzone } from "@tw/components/common/FileDropzone";
import { MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES } from "@tw/lib/attachmentMeta";
import { makeFile } from "@tw/lib/__tests__/testUtils";

// Regression coverage for the two pre-existing attachment pickers: the
// Browse button, their own drop box, validation, dedupe and remove must
// behave exactly as before drag/paste were added around them.

function Harness({
  Picker,
  onChange,
  maxFiles,
  initial = [],
}: {
  Picker: "dropzone" | "uploader";
  onChange?: (files: File[]) => void;
  maxFiles?: number;
  initial?: File[];
}) {
  const [files, setFiles] = useState<File[]>(initial);
  const handle = (next: File[]) => {
    setFiles(next);
    onChange?.(next);
  };
  return Picker === "dropzone" ? (
    <FileDropzone label="Files" files={files} onFilesChange={handle} />
  ) : (
    <AttachmentUploader files={files} onFilesChange={handle} maxFiles={maxFiles} />
  );
}

function dropOn(target: Element, files: File[]) {
  fireEvent.drop(target, { dataTransfer: { files, types: ["Files"] } });
}

describe.each([
  ["FileDropzone", "dropzone" as const],
  ["AttachmentUploader", "uploader" as const],
])("%s (existing behavior)", (_name, Picker) => {
  const user = userEvent.setup({ applyAccept: false });

  function fileInput(container: HTMLElement) {
    return container.querySelector('input[type="file"]') as HTMLInputElement;
  }

  it("Browse files opens the file picker", async () => {
    const { container } = render(<Harness Picker={Picker} />);
    const input = fileInput(container);
    const click = vi.spyOn(input, "click");
    await user.click(screen.getByRole("button", { name: /browse files/i }));
    expect(click).toHaveBeenCalled();
  });

  it("attaches a valid file chosen through the picker", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    await user.upload(fileInput(container), makeFile("invoice.pdf", "application/pdf"));
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ name: "invoice.pdf" })]);
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
  });

  it("attaches multiple files at once", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    await user.upload(fileInput(container), [makeFile("a.pdf"), makeFile("b.docx"), makeFile("c.png")]);
    expect(onChange.mock.lastCall![0]).toHaveLength(3);
  });

  it("attaches files dropped on its own drop box", () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    dropOn(container.querySelector("[data-attachment-dropzone]") ?? screen.getByText(/drag files here/i), [
      makeFile("dropped.pdf"),
    ]);
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ name: "dropped.pdf" })]);
  });

  it("rejects an unsupported file type with an inline error and keeps valid files", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    await user.upload(fileInput(container), [makeFile("ok.pdf"), makeFile("bad.exe")]);
    expect(onChange.mock.lastCall![0].map((f: File) => f.name)).toEqual(["ok.pdf"]);
    expect(screen.getByText(/"bad.exe" has an unsupported file type/)).toBeInTheDocument();
  });

  it("rejects an oversized file with an inline error", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    await user.upload(fileInput(container), makeFile("huge.pdf", "", MAX_ATTACHMENT_SIZE_BYTES + 1));
    expect(onChange.mock.lastCall![0]).toEqual([]);
    expect(screen.getByText(/exceeds the .*MB size limit/)).toBeInTheDocument();
  });

  it("enforces the maximum file count", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} />);
    const many = Array.from({ length: MAX_ATTACHMENT_FILES + 1 }, (_, i) => makeFile(`f${i}.pdf`));
    await user.upload(fileInput(container), many);
    expect(onChange.mock.lastCall![0]).toHaveLength(MAX_ATTACHMENT_FILES);
    expect(screen.getByText(new RegExp(`Only ${MAX_ATTACHMENT_FILES} files`))).toBeInTheDocument();
  });

  it("silently ignores a duplicate file", async () => {
    const original = makeFile("same.pdf");
    const duplicate = new File(["x"], "same.pdf", { lastModified: original.lastModified });
    Object.defineProperty(duplicate, "size", { value: original.size });
    const onChange = vi.fn();
    const { container } = render(<Harness Picker={Picker} onChange={onChange} initial={[original]} />);
    await user.upload(fileInput(container), duplicate);
    expect(onChange.mock.lastCall![0]).toEqual([original]);
    expect(screen.queryByText(/unsupported|exceeds|Only/)).not.toBeInTheDocument();
  });

  it("removes a single attachment and leaves the others", async () => {
    const onChange = vi.fn();
    render(<Harness Picker={Picker} onChange={onChange} initial={[makeFile("a.pdf"), makeFile("b.pdf")]} />);
    await user.click(screen.getByRole("button", { name: "Remove a.pdf" }));
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ name: "b.pdf" })]);
    const list = screen.getByRole("list");
    expect(within(list).queryByText("a.pdf")).not.toBeInTheDocument();
    expect(within(list).getByText("b.pdf")).toBeInTheDocument();
  });

  it("shows filename, size and an accessible remove button for each chip", () => {
    render(<Harness Picker={Picker} initial={[makeFile("claim.pdf", "", 2048)]} />);
    expect(screen.getByText("claim.pdf")).toBeInTheDocument();
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove claim.pdf" })).toBeInTheDocument();
  });
});

describe("AttachmentUploader maxFiles override (Forward's remaining slots)", () => {
  it("honors a lowered cap", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const onChange = vi.fn();
    const { container } = render(<Harness Picker="uploader" onChange={onChange} maxFiles={2} />);
    await user.upload(container.querySelector('input[type="file"]') as HTMLInputElement, [
      makeFile("a.pdf"),
      makeFile("b.pdf"),
      makeFile("c.pdf"),
    ]);
    expect(onChange.mock.lastCall![0]).toHaveLength(2);
    expect(screen.getByText(/Only 2 files/)).toBeInTheDocument();
  });
});
