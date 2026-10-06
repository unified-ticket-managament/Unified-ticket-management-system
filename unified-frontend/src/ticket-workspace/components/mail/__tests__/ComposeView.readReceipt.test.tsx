import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ComposeView, type ComposeInitialValues } from "@tw/components/mail/ComposeView";
import * as inboxApi from "@tw/api/inbox";

// "Request read receipt" in New Email / reopened Compose drafts: hidden
// unless the backend has the feature on, off by default, sent with the
// message, saved with the draft and restored on reopen, and never shown
// (or sent) for Forward.

vi.mock("@/hooks/use-email-signatures", () => ({
  useEmailSignatures: () => ({ data: undefined }),
}));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: {
      user_id: "u1",
      role: "Site Lead",
      permissions: ["communication:create", "communication:reply_external"],
    },
  }),
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
vi.mock("@tw/components/common/DistributionListMultiSelect", () => ({
  DistributionListMultiSelect: () => null,
}));
vi.mock("@tw/components/common/MultiRecipientCombobox", () => ({ MultiRecipientCombobox: () => null }));
vi.mock("@tw/api/inbox", () => ({
  createComposeDraft: vi.fn(),
  discardComposeDraft: vi.fn(),
  saveComposeDraft: vi.fn(),
  uploadComposeInlineImage: vi.fn(),
}));
vi.mock("@tw/api/interaction", () => ({ listInternalNoteRecipients: vi.fn().mockResolvedValue([]) }));
vi.mock("@tw/api/clients", () => ({ listClientContacts: vi.fn().mockResolvedValue([]) }));

const client = {
  client_id: "c1",
  name: "Acme Clinic",
  company_name: "Acme",
  is_active: true,
  inbox_email: "acme@example.com",
  account_manager_id: "u1",
} as unknown as Parameters<typeof ComposeView>[0]["clients"][number];

const READY: ComposeInitialValues = {
  clientId: "c1",
  toEmail: "to@example.com",
  subject: "Hello",
  message: "Body text",
};

function renderCompose(
  initialValues: ComposeInitialValues | undefined,
  extra: Partial<React.ComponentProps<typeof ComposeView>> = {}
) {
  const onSend = vi.fn().mockResolvedValue(undefined);
  const onForwardSend = vi.fn().mockResolvedValue(undefined);
  render(
    <ComposeView
      variant="panel"
      clients={[client]}
      categories={[]}
      clientsLoading={false}
      clientsError={false}
      initialValues={initialValues}
      isSending={false}
      onSend={onSend}
      onForwardSend={onForwardSend}
      onDiscard={vi.fn()}
      onBack={vi.fn()}
      {...extra}
    />
  );
  return { onSend, onForwardSend };
}

const checkbox = () => screen.getByRole("checkbox", { name: /request read receipt/i });
const queryCheckbox = () => screen.queryByRole("checkbox", { name: /request read receipt/i });
const isChecked = () => checkbox().getAttribute("data-state") === "checked";
// An untouched prefilled body counts as empty (Send stays disabled), so
// edit it first, the way a user would.
const type = (text: string) =>
  fireEvent.change(screen.getByLabelText("body"), { target: { value: text } });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(inboxApi.createComposeDraft).mockResolvedValue({
    interaction_id: "draft-1",
  } as Awaited<ReturnType<typeof inboxApi.createComposeDraft>>);
  vi.mocked(inboxApi.saveComposeDraft).mockResolvedValue({
    interaction_id: "draft-1",
  } as Awaited<ReturnType<typeof inboxApi.saveComposeDraft>>);
});

describe("visibility", () => {
  it("is hidden by default (feature off)", () => {
    renderCompose(READY);
    expect(queryCheckbox()).toBeNull();
  });

  it("shows unchecked once the feature is on", () => {
    renderCompose(READY, { readReceiptsEnabled: true });
    expect(checkbox()).toBeTruthy();
    expect(isChecked()).toBe(false);
  });

  it("is never shown for Forward, even with the feature on", () => {
    renderCompose(
      {
        mode: "forward",
        clientId: "c1",
        toEmail: "",
        subject: "Fwd: Claim",
        bodyHtml: "<p>Forwarded</p>",
        interactionId: "i1",
        originalAttachmentCount: 0,
        originalAttachments: [],
      },
      { readReceiptsEnabled: true }
    );
    expect(queryCheckbox()).toBeNull();
  });
});

describe("sending", () => {
  it("sends the flag when ticked", async () => {
    const { onSend } = renderCompose(READY, { readReceiptsEnabled: true });
    type("Hello");
    fireEvent.click(checkbox());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    });

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0].readReceiptRequested).toBe(true);
  });

  it("sends the flag as off by default", async () => {
    const { onSend } = renderCompose(READY, { readReceiptsEnabled: true });
    type("Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    });

    expect(onSend.mock.calls[0][0].readReceiptRequested).toBe(false);
  });

  it("never requests a receipt while the feature is off, even for a stale ticked draft", async () => {
    const { onSend } = renderCompose({ ...READY, readReceiptRequested: true });
    type("Hello");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    });

    expect(onSend.mock.calls[0][0].readReceiptRequested).toBe(false);
  });
});

describe("drafts", () => {
  it("Save Draft stores the flag when ticked", async () => {
    renderCompose(READY, { readReceiptsEnabled: true });
    fireEvent.click(checkbox());
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });

    const request = vi.mocked(inboxApi.createComposeDraft).mock.calls[0][0];
    expect(request.read_receipt_requested).toBe(true);
  });

  it("an unticked draft's request is unchanged (no flag key at all)", async () => {
    renderCompose(READY, { readReceiptsEnabled: true });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });

    const request = vi.mocked(inboxApi.createComposeDraft).mock.calls[0][0];
    expect("read_receipt_requested" in request).toBe(false);
  });

  it("reopening a ticked draft restores the checkbox, and later saves keep it", async () => {
    renderCompose(
      { ...READY, draftInteractionId: "draft-1", readReceiptRequested: true },
      { readReceiptsEnabled: true }
    );
    expect(isChecked()).toBe(true);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    });
    const [, request] = vi.mocked(inboxApi.saveComposeDraft).mock.calls[0];
    expect(request.read_receipt_requested).toBe(true);
  });
});
