import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";

// "Request read receipt" in the Reply / Reply All composer: hidden unless
// the backend has the feature on, off by default, travels with the send
// (ticketed) and with the saved draft (pre-ticket, whose draft-send
// endpoint takes no per-send options), and is never sent while the
// feature is off.

vi.mock("@/services", () => ({
  signatureService: { setDefault: vi.fn(), update: vi.fn(), list: vi.fn() },
}));
vi.mock("@/hooks/use-email-signatures", () => ({
  useEmailSignatures: () => ({ data: undefined }),
}));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));
vi.mock("@tw/components/mail/RichTextEditor", () => ({
  RichTextEditor: ({ value, onChange }: { value: string; onChange: (html: string) => void }) => (
    <div>
      <output data-testid="body">{value}</output>
      <textarea aria-label="body" onChange={(e) => onChange(`<p>${e.target.value}</p>`)} />
    </div>
  ),
  isRichTextEmpty: (html: string) => html.replace(/<[^>]*>/g, "").trim().length === 0,
}));
vi.mock("@tw/components/mail/SignatureSelector", () => ({ SignatureSelector: () => null }));

function setup(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  const props = {
    mode: "reply" as const,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Claim",
    isSending: false,
    isTicketed: true,
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
  render(<ReplyComposer {...props} />);
  // The three callbacks are always vitest mocks (a test may swap one for
  // another mock via `overrides`); say so for the type-checker.
  return props as typeof props & { onSend: Mock; onSaveDraft: Mock; onSendDraft: Mock };
}

const checkbox = () => screen.getByRole("checkbox", { name: /request read receipt/i });
const queryCheckbox = () => screen.queryByRole("checkbox", { name: /request read receipt/i });
const type = (text: string) =>
  fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });
const isChecked = () => checkbox().getAttribute("data-state") === "checked";

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.useRealTimers());

describe("visibility", () => {
  it("is hidden by default (feature off)", () => {
    setup();
    expect(queryCheckbox()).toBeNull();
    expect(screen.queryByText(/request read receipt/i)).toBeNull();
  });

  it("is hidden when the backend setting is explicitly off", () => {
    setup({ readReceiptsEnabled: false });
    expect(queryCheckbox()).toBeNull();
  });

  it.each([true, false])("shows once enabled, unchecked, for isTicketed=%s", (isTicketed) => {
    setup({ readReceiptsEnabled: true, isTicketed });
    expect(checkbox()).toBeTruthy();
    expect(isChecked()).toBe(false);
  });

  it("explains that receipts are optional and recipient-dependent", () => {
    setup({ readReceiptsEnabled: true });
    expect(screen.getByText(/depends on the recipient's mail system/i)).toBeTruthy();
  });
});

describe("ticketed send (Reply / Reply All)", () => {
  it.each(["reply", "replyAll"] as const)("%s sends the flag when ticked", (mode) => {
    const props = setup({ readReceiptsEnabled: true, mode });
    type("Hello");
    fireEvent.click(checkbox());
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));

    expect(props.onSend).toHaveBeenCalledTimes(1);
    expect(props.onSend.mock.calls[0][0].readReceiptRequested).toBe(true);
  });

  it("sends the flag as off when left unticked", () => {
    const props = setup({ readReceiptsEnabled: true });
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));

    expect(props.onSend.mock.calls[0][0].readReceiptRequested).toBe(false);
  });

  it("never requests a receipt while the feature is off, even for a stale ticked draft", () => {
    const props = setup({ readReceiptsEnabled: false, initialReadReceiptRequested: true });
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));

    expect(props.onSend.mock.calls[0][0].readReceiptRequested).toBe(false);
  });
});

describe("pre-ticket draft flow", () => {
  it("Save Draft persists the flag with the draft", async () => {
    const props = setup({ readReceiptsEnabled: true, isTicketed: false });
    type("Hello");
    fireEvent.click(checkbox());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });

    const call = props.onSaveDraft.mock.calls.at(-1)!;
    expect(call[4]).toBe(true);
  });

  it("Send saves the draft WITH the flag before the (option-less) draft send", async () => {
    const order: string[] = [];
    const props = setup({
      readReceiptsEnabled: true,
      isTicketed: false,
      onSaveDraft: vi.fn().mockImplementation(async (...args: unknown[]) => {
        order.push(`save:${String(args[4])}`);
        return true;
      }),
      onSendDraft: vi.fn().mockImplementation(async () => {
        order.push("send");
      }),
    });
    type("Hello");
    fireEvent.click(checkbox());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    });

    expect(order.at(-2)).toBe("save:true");
    expect(order.at(-1)).toBe("send");
    expect(props.onSendDraft).toHaveBeenCalledTimes(1);
  });

  it("an unticked draft saves the flag as off", async () => {
    const props = setup({ readReceiptsEnabled: true, isTicketed: false });
    type("Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });

    expect(props.onSaveDraft.mock.calls.at(-1)![4]).toBe(false);
  });

  it("autosave carries a toggle made after typing", async () => {
    vi.useFakeTimers();
    const props = setup({ readReceiptsEnabled: true, isTicketed: false });
    type("Hello");
    fireEvent.click(checkbox());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });

    expect(props.onSaveDraft).toHaveBeenCalled();
    expect(props.onSaveDraft.mock.calls.at(-1)![4]).toBe(true);
  });
});

describe("resuming a saved draft", () => {
  it("restores the ticked state", () => {
    setup({
      readReceiptsEnabled: true,
      isTicketed: false,
      hasExistingDraft: true,
      initialMessage: "Saved text",
      initialReadReceiptRequested: true,
    });
    expect(isChecked()).toBe(true);
  });

  it("a resumed ticked draft sends the flag", () => {
    const props = setup({
      readReceiptsEnabled: true,
      hasExistingDraft: true,
      initialMessage: "Saved text",
      initialReadReceiptRequested: true,
    });
    // An untouched resumed body counts as empty (Send is disabled until
    // something is edited), same as for any other composer.
    type("Edited after resuming");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));

    expect(props.onSend.mock.calls[0][0].readReceiptRequested).toBe(true);
  });
});
