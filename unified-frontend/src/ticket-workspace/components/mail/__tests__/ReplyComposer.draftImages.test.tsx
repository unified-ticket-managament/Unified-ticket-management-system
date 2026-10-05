import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";
import type { AttachmentMeta } from "@tw/types";

vi.mock("@/hooks/use-email-signatures", () => ({ useEmailSignatures: () => ({ data: undefined }) }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
// Exposes the HTML the composer hands the editor, so the test can see
// exactly what a reopened draft would render.
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ value }: { value: string }) => <div className="ProseMirror" data-testid="editor-value" data-value={value} />,
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({ DistributionListMultiSelect: () => null }));

const attachment = (id: string, over: Partial<AttachmentMeta> = {}): AttachmentMeta => ({
  id,
  filename: `${id}.png`,
  mime_type: "image/png",
  size: 100,
  download_url: `https://s/dl-${id}`,
  preview_url: `https://s/preview-${id}`,
  ...over,
});

function setup(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
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
    onSendDraft: vi.fn(),
    onDiscardDraft: vi.fn(),
    onUploadDraftAttachment: vi.fn(),
    onRemoveDraftAttachment: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
  return { ...render(<ReplyComposer {...props} />), props };
}

describe("reopening a saved draft with pasted images", () => {
  it("renders the saved cid: images with real URLs instead of broken references", () => {
    setup({
      hasExistingDraft: true,
      initialBodyHtml: '<p>Hi</p><img src="cid:img-1" data-local-id="l" data-content-id="img-1">',
      draftAttachments: [attachment("a1", { content_id: "img-1", is_inline: true, preview_url: "https://s/preview-img-1" })],
    });
    const html = screen.getByTestId("editor-value").getAttribute("data-value")!;
    expect(html).toContain("https://s/preview-img-1");
    expect(html).not.toContain("cid:img-1");
  });

  it("does not touch a draft body with no cid references", () => {
    setup({ hasExistingDraft: true, initialBodyHtml: "<p>plain draft</p>" });
    expect(screen.getByTestId("editor-value").getAttribute("data-value")).toBe("<p>plain draft</p>");
  });
});

describe("removing a draft attachment", () => {
  it("ignores a second click while a delete is still in flight, then re-enables", async () => {
    let finish: (ok: boolean) => void = () => {};
    const onRemoveDraftAttachment = vi.fn(() => new Promise<boolean>((resolve) => (finish = resolve)));
    setup({ draftAttachments: [attachment("one"), attachment("two")], onRemoveDraftAttachment });

    fireEvent.click(screen.getByRole("button", { name: "Remove one.png" }));
    expect(screen.getByRole("button", { name: "Remove one.png" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove two.png" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove two.png" }));
    expect(onRemoveDraftAttachment).toHaveBeenCalledTimes(1);
    expect(onRemoveDraftAttachment).toHaveBeenCalledWith("one");

    finish(true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove two.png" })).toBeEnabled());
  });

  it("re-enables after a failed delete so the user can retry", async () => {
    const onRemoveDraftAttachment = vi.fn().mockResolvedValue(false);
    setup({ draftAttachments: [attachment("one")], onRemoveDraftAttachment });
    fireEvent.click(screen.getByRole("button", { name: "Remove one.png" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove one.png" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Remove one.png" }));
    expect(onRemoveDraftAttachment).toHaveBeenCalledTimes(2);
  });
});
