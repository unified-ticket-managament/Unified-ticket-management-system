import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ReplyComposer } from "@tw/components/mail/ReplyComposer";

// The Reply / Reply All Subject is an editable field: pre-filled with the
// same "Re: <subject>" as before (or the saved draft's subject), kept in
// composer state, and the CURRENT value is what Send / Save Draft use.

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

function makeProps(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  return {
    mode: "reply" as const,
    toEmail: "client@example.com",
    contacts: [],
    subject: "Claim Status",
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
}

function setup(overrides: Partial<React.ComponentProps<typeof ReplyComposer>> = {}) {
  const props = makeProps(overrides);
  const view = render(<ReplyComposer {...props} />);
  return { props: props as typeof props & { onSend: Mock; onSaveDraft: Mock }, view };
}

const subjectInput = () => screen.getByLabelText("Subject") as HTMLInputElement;
const type = (text: string) =>
  fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });
const setSubject = (value: string) => fireEvent.change(subjectInput(), { target: { value } });

beforeEach(() => vi.clearAllMocks());

describe("initial subject", () => {
  it.each(["reply", "replyAll"] as const)("%s is pre-filled with Re: <subject>, editable", (mode) => {
    setup({ mode });
    expect(subjectInput().value).toBe("Re: Claim Status");
    expect(subjectInput().readOnly).toBe(false);
    expect(subjectInput().disabled).toBe(false);
  });

  it("does not double the Re: prefix", () => {
    setup({ subject: "RE: Claim Status" });
    expect(subjectInput().value).toBe("RE: Claim Status");
  });

  it("starts from a resumed draft's saved subject", () => {
    setup({ hasExistingDraft: true, initialSubject: "Saved Subject" });
    expect(subjectInput().value).toBe("Saved Subject");
  });
});

describe("send uses the current subject", () => {
  it("unedited reply sends the generated subject", () => {
    const { props } = setup();
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));
    expect(props.onSend.mock.calls[0][0].subject).toBe("Re: Claim Status");
  });

  it.each(["reply", "replyAll"] as const)("%s sends the edited subject", (mode) => {
    const { props } = setup({ mode });
    setSubject("Re: [URGENT] Claim #123 - Patient's Account");
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));
    expect(props.onSend.mock.calls[0][0].subject).toBe("Re: [URGENT] Claim #123 - Patient's Account");
  });

  it("editing the subject leaves recipients untouched", () => {
    const { props } = setup({ initialCc: ["cc@example.com"], initialBcc: ["bcc@example.com"] });
    setSubject("Updated Claim Status - Patient ABC");
    type("Hello");
    fireEvent.click(screen.getByRole("button", { name: /send reply/i }));
    const sent = props.onSend.mock.calls[0][0];
    expect(sent.to).toEqual(["client@example.com"]);
    expect(sent.cc).toEqual(["cc@example.com"]);
    expect(sent.bcc).toEqual(["bcc@example.com"]);
  });

  it("keeps the edited subject when switching Reply -> Reply All", () => {
    const { props, view } = setup();
    setSubject("Changed");
    view.rerender(<ReplyComposer {...props} mode="replyAll" />);
    expect(subjectInput().value).toBe("Changed");
  });

  it("a different thread resets to that thread's own default", () => {
    const { props, view } = setup();
    setSubject("Changed");
    view.rerender(<ReplyComposer {...props} subject="Other Thread" />);
    expect(subjectInput().value).toBe("Re: Other Thread");
  });

  it("two composers keep independent subjects", () => {
    const first = makeProps();
    const second = makeProps({ subject: "Other" });
    render(
      <>
        <div data-testid="a"><ReplyComposer {...first} /></div>
        <div data-testid="b"><ReplyComposer {...second} /></div>
      </>
    );
    const inputs = screen.getAllByLabelText("Subject") as HTMLInputElement[];
    fireEvent.change(inputs[0], { target: { value: "Only A" } });
    expect(inputs[0].value).toBe("Only A");
    expect(inputs[1].value).toBe("Re: Other");
  });
});

describe("draft saving", () => {
  it("Save Draft (pre-ticket) carries the edited subject as the last argument", async () => {
    const { props } = setup({ isTicketed: false });
    setSubject("Updated Subject");
    type("Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });
    expect(props.onSaveDraft.mock.calls.at(-1)![5]).toBe("Updated Subject");
  });

  it("pre-ticket Send saves the edited subject before the draft send", async () => {
    const order: string[] = [];
    const { props } = setup({
      isTicketed: false,
      onSaveDraft: vi.fn().mockImplementation(async (...a: unknown[]) => {
        order.push(`save:${String(a[5])}`);
        return true;
      }),
      onSendDraft: vi.fn().mockImplementation(async () => {
        order.push("send");
      }),
    });
    setSubject("Documents Required");
    type("Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    });
    expect(order.slice(-2)).toEqual(["save:Documents Required", "send"]);
    expect(props.onSendDraft).toHaveBeenCalledTimes(1);
  });
});
