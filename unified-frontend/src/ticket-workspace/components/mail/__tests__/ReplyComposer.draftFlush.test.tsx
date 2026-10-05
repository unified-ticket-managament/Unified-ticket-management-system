import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";

vi.mock("@/hooks/use-email-signatures", () => ({ useEmailSignatures: () => ({ data: undefined }) }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
// Minimal editor stand-in that drives `onChange` the way TipTap does.
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ onChange }: { onChange: (html: string) => void }) => (
    <div className="ProseMirror">
      <textarea aria-label="body" onChange={(e) => onChange(`<p>${e.target.value}</p>`)} />
    </div>
  ),
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));

function setup(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  const props = {
    mode: "reply" as const,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Hello",
    isSending: false,
    isTicketed: false,
    draftAttachments: [],
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

const type = (text: string) => fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("ReplyComposer draft autosave on close", () => {
  it("debounced autosave still fires after 1.2s", async () => {
    const { props } = setup();
    type("Dear client");
    expect(props.onSaveDraft).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(props.onSaveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(props.onSaveDraft).mock.calls[0][0]).toBe("Dear client");
  });

  it("saves typing from inside the debounce window when the composer unmounts (e.g. the email window closes)", () => {
    const { props, unmount } = setup();
    type("Almost forgot this");
    expect(props.onSaveDraft).not.toHaveBeenCalled();
    unmount();
    expect(props.onSaveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(props.onSaveDraft).mock.calls[0][0]).toBe("Almost forgot this");
  });

  it("does not double-save when the debounce already fired before unmount", async () => {
    const { props, unmount } = setup();
    type("Already saved");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    unmount();
    expect(props.onSaveDraft).toHaveBeenCalledTimes(1);
  });

  it("saves only the latest text, once, after several quick edits", () => {
    const { props, unmount } = setup();
    type("a");
    type("ab");
    type("abc");
    unmount();
    expect(props.onSaveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(props.onSaveDraft).mock.calls[0][0]).toBe("abc");
  });

  it("saves nothing when nothing was typed", () => {
    const { props, unmount } = setup();
    unmount();
    expect(props.onSaveDraft).not.toHaveBeenCalled();
  });

  it("saves nothing for a cleared (empty) body", () => {
    const { props, unmount } = setup();
    type("temp");
    type("");
    unmount();
    expect(props.onSaveDraft).not.toHaveBeenCalled();
  });

  it("does not resurrect the draft after a ticketed Send", async () => {
    const { props, unmount } = setup({ isTicketed: true });
    type("Final answer");
    fireEvent.click(screen.getByRole("button", { name: "Send Reply" }));
    expect(props.onSend).toHaveBeenCalledTimes(1);
    unmount();
    expect(props.onSaveDraft).not.toHaveBeenCalled();
  });

  it("does not resurrect the draft after Discard Draft", async () => {
    const { props, unmount } = setup();
    type("never mind");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /discard draft/i }));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(props.onDiscardDraft).toHaveBeenCalledTimes(1);
    unmount();
    expect(props.onSaveDraft).not.toHaveBeenCalled();
  });

  it("saves again if the user keeps editing after a failed Send", async () => {
    const { props, unmount } = setup({ isTicketed: true });
    type("first try");
    fireEvent.click(screen.getByRole("button", { name: "Send Reply" })); // parent reports failure by not unmounting
    type("first try, edited");
    unmount();
    expect(props.onSaveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(props.onSaveDraft).mock.calls[0][0]).toBe("first try, edited");
  });
});
