import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";
import { MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES } from "@tw/lib/attachmentMeta";
import { fakeDataTransfer, makeFile } from "@tw/lib/__tests__/testUtils";
import type { AttachmentMeta } from "@tw/types";

const pushToast = vi.fn();
vi.mock("@/hooks/use-email-signatures", () => ({ useEmailSignatures: () => ({ data: undefined }) }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));

// TipTap has its own jsdom-hostile internals and its paste/drop handling
// is covered separately (lib/clipboardPaste.ts is untouched). What matters
// here is the `.ProseMirror` marker the composer-level intake keys on.
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: () => <div className="ProseMirror" data-testid="editor" contentEditable suppressContentEditableWarning />,
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));

const pdf = makeFile("invoice.pdf", "application/pdf");
const png = makeFile("screenshot.png", "image/png");

function draftAttachment(i: number): AttachmentMeta {
  return {
    id: `att-${i}`,
    filename: `existing-${i}.pdf`,
    size: 100,
    download_url: "/x",
    preview_url: "/x",
  } as unknown as AttachmentMeta;
}

function renderComposer(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  const props = {
    mode: "reply" as const,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Hello",
    isSending: false,
    isTicketed: false,
    draftAttachments: [] as AttachmentMeta[],
    onCancel: vi.fn(),
    onSend: vi.fn(),
    onSaveDraft: vi.fn().mockResolvedValue(true),
    onSendDraft: vi.fn().mockResolvedValue(undefined),
    onDiscardDraft: vi.fn().mockResolvedValue(undefined),
    onUploadDraftAttachment: vi.fn().mockResolvedValue(undefined),
    onRemoveDraftAttachment: vi.fn(),
    ...overrides,
  };
  const utils = render(<ReplyComposer {...props} />);
  return { ...utils, props };
}

function paste(target: Element, init: Parameters<typeof fakeDataTransfer>[0]) {
  const event = createEvent.paste(target, { clipboardData: fakeDataTransfer(init) });
  fireEvent(target, event);
  return event;
}

function drop(target: Element, files: File[]) {
  const event = createEvent.drop(target, { dataTransfer: fakeDataTransfer({ files }) });
  fireEvent(target, event);
  return event;
}

beforeEach(() => pushToast.mockClear());

describe("ReplyComposer — unticketed (immediate draft upload)", () => {
  it("existing Attach Files button still opens the picker and uploads", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container, props } = renderComposer();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    await user.click(screen.getByRole("button", { name: /attach files/i }));
    expect(click).toHaveBeenCalled();
    await user.upload(input, pdf);
    await waitFor(() => expect(props.onUploadDraftAttachment).toHaveBeenCalledWith([pdf]));
  });

  it("a PDF dropped on the composer uploads through the same draft path", async () => {
    const { props } = renderComposer();
    const event = drop(screen.getByTestId("editor"), [pdf]);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(props.onUploadDraftAttachment).toHaveBeenCalledWith([pdf]));
  });

  it("a PDF pasted into the composer uploads through the same draft path", async () => {
    const { props } = renderComposer();
    paste(screen.getByTestId("editor"), { files: [pdf] });
    await waitFor(() => expect(props.onUploadDraftAttachment).toHaveBeenCalledWith([pdf]));
  });

  it("an image dropped outside the editor becomes an attachment", async () => {
    const { props } = renderComposer();
    drop(screen.getByText("Reply"), [png]);
    await waitFor(() => expect(props.onUploadDraftAttachment).toHaveBeenCalledWith([png]));
  });

  it("an image pasted/dropped inside the editor is left to the editor — not uploaded as an attachment", () => {
    const { props } = renderComposer();
    paste(screen.getByTestId("editor"), { files: [png] });
    drop(screen.getByTestId("editor"), [png]);
    expect(props.onUploadDraftAttachment).not.toHaveBeenCalled();
  });

  it("rejects an unsupported file with the existing inline error and uploads only valid ones", async () => {
    const { props } = renderComposer();
    drop(screen.getByTestId("editor"), [makeFile("bad.exe"), pdf]);
    await waitFor(() => expect(props.onUploadDraftAttachment).toHaveBeenCalledWith([pdf]));
    expect(screen.getByText(/"bad.exe" has an unsupported file type/)).toBeInTheDocument();
  });

  it("rejects an oversized file", () => {
    const { props } = renderComposer();
    drop(screen.getByTestId("editor"), [makeFile("huge.pdf", "", MAX_ATTACHMENT_SIZE_BYTES + 1)]);
    expect(props.onUploadDraftAttachment).not.toHaveBeenCalled();
    expect(screen.getByText(/exceeds the .*MB size limit/)).toBeInTheDocument();
  });

  it("plain-text paste is untouched", () => {
    const { props } = renderComposer();
    const event = paste(screen.getByTestId("editor"), { data: { "text/plain": "Please review this ticket." } });
    expect(event.defaultPrevented).toBe(false);
    expect(props.onUploadDraftAttachment).not.toHaveBeenCalled();
  });

  it("stops accepting dropped files once the draft already holds the maximum, like the Attach button", () => {
    const full = Array.from({ length: MAX_ATTACHMENT_FILES }, (_, i) => draftAttachment(i));
    const { props } = renderComposer({ draftAttachments: full });
    expect(screen.getByRole("button", { name: /attach files/i })).toBeDisabled();
    const event = drop(screen.getByTestId("editor"), [pdf]);
    expect(props.onUploadDraftAttachment).not.toHaveBeenCalled();
    // swallowed rather than letting the browser navigate to the file
    expect(event.defaultPrevented).toBe(true);
  });

  it("removing an uploaded draft attachment still works", async () => {
    const user = userEvent.setup();
    const { props } = renderComposer({ draftAttachments: [draftAttachment(1), draftAttachment(2)] });
    await user.click(screen.getByRole("button", { name: "Remove existing-1.pdf" }));
    expect(props.onRemoveDraftAttachment).toHaveBeenCalledWith("att-1");
  });
});

describe("ReplyComposer — ticketed (local files, uploaded at Send)", () => {
  it("existing Attach Files toggle still reveals the uploader", async () => {
    const user = userEvent.setup();
    renderComposer({ isTicketed: true });
    expect(screen.queryByText(/drag files here/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /attach files/i }));
    expect(screen.getByText(/drag files here/i)).toBeInTheDocument();
  });

  it("a pasted PDF appears as an attachment chip (revealing the uploader) and nothing is uploaded yet", () => {
    const { props } = renderComposer({ isTicketed: true });
    paste(screen.getByTestId("editor"), { files: [pdf] });
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /attach files \(1\)/i })).toBeInTheDocument();
    expect(props.onUploadDraftAttachment).not.toHaveBeenCalled();
    expect(props.onSend).not.toHaveBeenCalled();
  });

  it("a dropped PDF appears as a chip and can be removed independently of other files", async () => {
    const user = userEvent.setup();
    renderComposer({ isTicketed: true });
    drop(screen.getByTestId("editor"), [pdf, makeFile("notes.txt", "text/plain")]);
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove invoice.pdf" }));
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
  });

  it("reports a rejected dropped file through the existing toast and keeps the valid ones", () => {
    renderComposer({ isTicketed: true });
    drop(screen.getByTestId("editor"), [makeFile("bad.exe"), pdf]);
    expect(screen.getByText("invoice.pdf")).toBeInTheDocument();
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("unsupported file type"), "error");
  });

  it("silently ignores a duplicate pasted file (existing dedupe)", () => {
    renderComposer({ isTicketed: true });
    paste(screen.getByTestId("editor"), { files: [pdf] });
    paste(screen.getByTestId("editor"), { files: [pdf] });
    expect(screen.getAllByText("invoice.pdf")).toHaveLength(1);
    expect(pushToast).not.toHaveBeenCalled();
  });

  it("ignores intake while a send is in flight", () => {
    renderComposer({ isTicketed: true, isSending: true });
    const event = drop(screen.getByTestId("editor"), [pdf]);
    expect(screen.queryByText("invoice.pdf")).not.toBeInTheDocument();
    expect(event.defaultPrevented).toBe(true);
  });
});
