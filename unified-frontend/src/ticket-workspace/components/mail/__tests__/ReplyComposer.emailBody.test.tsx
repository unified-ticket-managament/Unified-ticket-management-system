import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";

// Reply and Reply All share the one ReplyComposer/RichTextEditor; this
// pins what both actually submit: the plain-text `message` exactly as
// before, plus the email-ready body_html (inline paragraph spacing +
// default font wrapper) for sends AND for saved drafts (which the
// server later sends verbatim).

vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ onChange }: { onChange: (html: string) => void }) => (
    <div className="ProseMirror">
      <textarea
        aria-label="body"
        onChange={(e) => onChange(e.target.value.split("\n\n").map((p) => `<p>${p}</p>`).join(""))}
      />
    </div>
  ),
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));

function setup(mode: "reply" | "replyAll", isTicketed: boolean) {
  const props = {
    mode,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Hello",
    isSending: false,
    isTicketed,
    draftAttachments: [],
    onCancel: vi.fn(),
    onSend: vi.fn(),
    onSaveDraft: vi.fn().mockResolvedValue(true),
    onSendDraft: vi.fn().mockResolvedValue(undefined),
    onDiscardDraft: vi.fn().mockResolvedValue(undefined),
    onUploadDraftAttachment: vi.fn().mockResolvedValue(undefined),
    onRemoveDraftAttachment: vi.fn(),
  };
  render(<ReplyComposer {...props} />);
  return props;
}

const type = (text: string) => fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe.each(["reply", "replyAll"] as const)("%s email body", (mode) => {
  it("sends plain message unchanged plus email-formatted body_html", () => {
    const props = setup(mode, true);
    type("Hello John,\n\nThank you.");
    fireEvent.click(screen.getByRole("button", { name: "Send Reply" }));
    const payload = vi.mocked(props.onSend).mock.calls[0][0];
    expect(payload.message).toBe("Hello John,\nThank you.");
    expect(payload.bodyHtml).toContain("font-family:'Times New Roman', Times, serif");
    expect(payload.bodyHtml).toContain('<p style="margin-top:0;margin-bottom:10px">Hello John,</p>');
  });

  it("saves drafts as the same email-ready HTML", async () => {
    const props = setup(mode, false);
    type("Draft text");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    const [message, , , bodyHtml] = vi.mocked(props.onSaveDraft).mock.calls[0];
    expect(message).toBe("Draft text");
    expect(bodyHtml).toContain('<p style="margin-top:0;margin-bottom:10px">Draft text</p>');
  });
});
