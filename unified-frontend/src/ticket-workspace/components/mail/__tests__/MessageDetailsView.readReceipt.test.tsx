import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMailFeatures, replyToInteraction } from "@tw/api/inbox";
import { replyToClient, saveTicketReplyDraft } from "@tw/api/interaction";
import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import { resetMailFeaturesCacheForTests } from "@tw/hooks/useMailFeatures";
import type { InteractionResponse, OpenEmailResponse, ReadReceiptStatus } from "@tw/types";

// Read-receipt status in the thread (per outbound message, per
// recipient) and how MessageDetailsView feeds the composer: the backend
// feature switch and a resumed draft's saved checkbox state.

type ComposerProps = {
  readReceiptsEnabled?: boolean;
  initialReadReceiptRequested?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [callback: string]: any;
};
const composerProps = vi.fn<(props: ComposerProps) => void>();
vi.mock("@tw/components/mail/ReplyComposer", () => ({
  ReplyComposer: (props: ComposerProps) => {
    composerProps(props);
    return <div data-testid="reply-composer" />;
  },
}));
vi.mock("@tw/components/sla/SlaFirstResponseBadge", () => ({ SlaFirstResponseBadge: () => null }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({
    setSelectedEmail: vi.fn(),
    allCategories: [],
    allCategoriesLoading: false,
    allCategoriesError: false,
  }),
}));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: {
      user_id: "u1",
      signature_html: null,
      permissions: ["communication:reply_external", "communication:archive"],
    },
  }),
}));
vi.mock("@/services", () => ({
  authService: { me: vi.fn().mockResolvedValue({ permissions: ["communication:reply_external"] }) },
}));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ refreshUser: vi.fn() }),
}));
vi.mock("@tw/api/inbox", () => ({
  archiveInteraction: vi.fn(),
  replyToInteraction: vi.fn(),
  uploadDraftInlineImage: vi.fn(),
  getMailFeatures: vi.fn(),
}));
vi.mock("@tw/api/agent", () => ({ listAssignableAgents: vi.fn().mockResolvedValue({ me: null, groups: [] }) }));
vi.mock("@tw/api/clients", () => ({ listClientContacts: vi.fn().mockResolvedValue([]) }));
vi.mock("@tw/api/interaction", () => ({
  discardTicketReplyDraft: vi.fn(),
  downloadAttachmentFile: vi.fn(),
  getTicketReplyDraft: vi.fn().mockResolvedValue(null),
  replyToClient: vi.fn(),
  retrySend: vi.fn(),
  saveTicketReplyDraft: vi.fn(),
  uploadAttachment: vi.fn(),
  uploadTicketInlineImage: vi.fn(),
}));
vi.mock("@tw/api/ticket", () => ({
  attachInteractionToTicket: vi.fn(),
  createTicketFromInteraction: vi.fn(),
  listTickets: vi.fn().mockResolvedValue([]),
}));

function reply(
  id: string,
  overrides: Partial<InteractionResponse> = {},
  envelopeExtra: Record<string, unknown> = {}
): InteractionResponse {
  return {
    interaction_id: id,
    ticket_id: null,
    interaction_type: "REPLY",
    status: "ASSIGNED",
    direction: "OUTBOUND",
    performed_by: "u1",
    payload: {
      message: "Reply text",
      envelope: {
        from_name: "Agent",
        from_email: "support@example.com",
        to_email: "client@example.com",
        ...envelopeExtra,
      },
    },
    is_visible: true,
    removed_by: null,
    removed_at: null,
    message_id: null,
    created_at: "2026-01-01T11:00:00Z",
    ...overrides,
  };
}

function makeEmail(overrides: Partial<OpenEmailResponse> = {}): OpenEmailResponse {
  return {
    interaction_id: "i1",
    ticket_id: null,
    client_id: null,
    client_name: "Acme Clinic",
    to_email: "support@example.com",
    to_emails: [],
    from_email: "client@example.com",
    from_name: "Client",
    cc: [],
    bcc: [],
    to_recipients: [],
    subject: "Printer is down",
    body: "Hello, the printer is down.",
    message_id: null,
    received_at: "2026-01-01T10:00:00Z",
    status: "PENDING",
    claimed_by: null,
    claimed_by_name: null,
    account_manager_name: null,
    ticket_priority: null,
    ticket_category: null,
    ticket_status: null,
    tags: [],
    folder_id: null,
    is_read: true,
    draft_message: null,
    draft_cc: [],
    draft_bcc: [],
    draft_attachments: [],
    attachments: [],
    replies: [],
    recommended_ticket_id: null,
    recommended_ticket_reason: null,
    ...overrides,
  };
}

function renderView(email: OpenEmailResponse) {
  return render(
    <MemoryRouter>
      <MessageDetailsView
        variant="panel"
        email={email}
        folders={[]}
        onBack={vi.fn()}
        onRefreshList={vi.fn()}
        onRefreshMessage={vi.fn()}
        onForward={vi.fn()}
        onSaveDraft={vi.fn()}
        onSendDraft={vi.fn()}
        onDiscardDraft={vi.fn()}
        onUploadDraftAttachment={vi.fn()}
        onRemoveDraftAttachment={vi.fn()}
        onUpdateTags={vi.fn()}
        onAssignFolder={vi.fn()}
        onMarkRead={vi.fn()}
        onMarkUnread={vi.fn()}
      />
    </MemoryRouter>
  );
}

const receipt = (
  recipient_email: string,
  status: ReadReceiptStatus["status"],
  read_at: string | null = null
): ReadReceiptStatus => ({ recipient_email, status, read_at });

beforeEach(() => {
  composerProps.mockClear();
  // Call history must not leak between tests (assertions read calls[0]).
  vi.mocked(replyToInteraction).mockClear();
  vi.mocked(replyToClient).mockClear();
  vi.mocked(saveTicketReplyDraft).mockClear();
  resetMailFeaturesCacheForTests();
  vi.mocked(getMailFeatures).mockReset();
  vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: false });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe("read-receipt status in the thread", () => {
  it("shows one line per recipient: received with its time, or no receipt", () => {
    renderView(
      makeEmail({
        replies: [
          reply("r1", {
            read_receipts: [
              receipt("a@example.com", "CONFIRMED", "2026-01-01T12:00:00Z"),
              receipt("b@example.com", "REQUESTED"),
            ],
          }),
        ],
      })
    );

    const list = screen.getByRole("list", { name: "Read receipts" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("a@example.com");
    expect(rows[0].textContent).toMatch(/Read receipt received · /);
    expect(rows[1].textContent).toContain("b@example.com");
    expect(rows[1].textContent).toContain("No receipt received");
  });

  it("never says unread / not read, and never claims the person read it", () => {
    renderView(
      makeEmail({
        replies: [
          reply("r1", {
            read_receipts: [
              receipt("a@example.com", "CONFIRMED", "2026-01-01T12:00:00Z"),
              receipt("b@example.com", "REQUESTED"),
            ],
          }),
        ],
      })
    );

    const text = screen.getByRole("list", { name: "Read receipts" }).textContent ?? "";
    expect(text).not.toMatch(/unread/i);
    expect(text).not.toMatch(/not read/i);
    expect(text).not.toMatch(/opened at|read it|was read/i);
  });

  it("a message that asked for a receipt but has no rows yet shows a neutral line", () => {
    renderView(makeEmail({ replies: [reply("r1", {}, { read_receipt_requested: true })] }));

    expect(screen.getByText("Read receipt requested")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Read receipts" })).toBeNull();
  });

  it("shows nothing for a message that never requested a receipt", () => {
    renderView(makeEmail({ replies: [reply("r1")] }));

    expect(screen.queryByRole("list", { name: "Read receipts" })).toBeNull();
    expect(screen.queryByText(/read receipt/i)).toBeNull();
  });

  it("never shows receipt state under an inbound client message", () => {
    renderView(
      makeEmail({
        replies: [
          {
            ...reply("r2"),
            interaction_type: "EMAIL",
            direction: "INBOUND",
            payload: { body: "Thanks", from_email: "client@example.com", from_name: "Client" },
            read_receipts: [receipt("a@example.com", "CONFIRMED")],
          },
        ],
      })
    );

    expect(screen.queryByRole("list", { name: "Read receipts" })).toBeNull();
  });

  it("an outbound Compose root shows its own per-recipient state", () => {
    renderView(
      makeEmail({ read_receipts: [receipt("a@example.com", "CONFIRMED", "2026-01-01T12:00:00Z")] })
    );

    expect(screen.getByRole("list", { name: "Read receipts" }).textContent).toContain(
      "a@example.com"
    );
  });

  it("explains that receipts are optional (tooltip text)", () => {
    renderView(
      makeEmail({ replies: [reply("r1", { read_receipts: [receipt("a@example.com", "REQUESTED")] })] })
    );

    expect(screen.getByRole("list", { name: "Read receipts" })).toHaveAttribute(
      "title",
      "Read receipts are optional and depend on the recipient's mail system."
    );
  });
});

describe("feeding the composer", () => {
  const withDraft = (overrides: Partial<OpenEmailResponse> = {}) =>
    makeEmail({ draft_message: "Saved draft", ...overrides });

  it("passes the feature switch as OFF until (and unless) the backend says on", async () => {
    renderView(withDraft());
    await screen.findByTestId("reply-composer");

    expect(composerProps.mock.calls.at(-1)![0].readReceiptsEnabled).toBe(false);
  });

  it("passes the feature switch as ON once the backend reports it (loading, then loaded)", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: true });
    renderView(withDraft());
    await screen.findByTestId("reply-composer");

    // First render: still loading, so off; then the lookup resolves.
    expect(composerProps.mock.calls[0][0].readReceiptsEnabled).toBe(false);
    await waitFor(() =>
      expect(composerProps.mock.calls.at(-1)![0].readReceiptsEnabled).toBe(true)
    );
  });

  it("a failed feature lookup leaves the feature off", async () => {
    vi.mocked(getMailFeatures).mockRejectedValue(new Error("network"));
    renderView(withDraft());
    await screen.findByTestId("reply-composer");

    await waitFor(() => expect(getMailFeatures).toHaveBeenCalled());
    expect(composerProps.mock.calls.at(-1)![0].readReceiptsEnabled).toBe(false);
  });

  it("restores a resumed draft's ticked checkbox", async () => {
    renderView(withDraft({ draft_read_receipt_requested: true }));
    await screen.findByTestId("reply-composer");

    expect(composerProps.mock.calls.at(-1)![0].initialReadReceiptRequested).toBe(true);
  });

  it("a resumed draft without the flag starts unchecked", async () => {
    renderView(withDraft());
    await screen.findByTestId("reply-composer");

    expect(composerProps.mock.calls.at(-1)![0].initialReadReceiptRequested).toBe(false);
  });

  it("a brand-new reply starts unchecked", async () => {
    const user = userEvent.setup();
    renderView(makeEmail());
    await user.click(screen.getByRole("button", { name: /^reply$/i }));
    await screen.findByTestId("reply-composer");

    expect(composerProps.mock.calls.at(-1)![0].initialReadReceiptRequested).toBe(false);
  });
});


// ---------------------------------------------------------------
// The handlers that carry the flag from the composer to the API
// ---------------------------------------------------------------

const SEND = {
  message: "Hello",
  bodyHtml: "<p>Hello</p>",
  cc: [],
  bcc: [],
  files: [],
  to: ["client@example.com"],
  distributionListIds: [],
};

async function composerFor(email: OpenEmailResponse) {
  renderView(email);
  await screen.findByTestId("reply-composer");
  return () => composerProps.mock.calls.at(-1)![0];
}

describe("pre-ticket send (replyToInteraction)", () => {
  it("sends read_receipt_requested when the composer reports it ticked", async () => {
    const composer = await composerFor(makeEmail({ draft_message: "Saved draft" }));
    await composer().onSend({ ...SEND, readReceiptRequested: true });

    expect(replyToInteraction).toHaveBeenCalledTimes(1);
    expect(vi.mocked(replyToInteraction).mock.calls[0][1].read_receipt_requested).toBe(true);
  });

  it.each([false, undefined])("an unticked send (%s) carries no flag at all", async (flag) => {
    const composer = await composerFor(makeEmail({ draft_message: "Saved draft" }));
    await composer().onSend({ ...SEND, readReceiptRequested: flag });

    expect("read_receipt_requested" in vi.mocked(replyToInteraction).mock.calls[0][1]).toBe(false);
  });

  it("Reply All carries it too", async () => {
    const user = userEvent.setup();
    renderView(makeEmail());
    await user.click(screen.getByRole("button", { name: /reply all/i }));
    await screen.findByTestId("reply-composer");
    await composerProps.mock.calls.at(-1)![0].onSend({ ...SEND, readReceiptRequested: true });

    const body = vi.mocked(replyToInteraction).mock.calls[0][1];
    expect(body.reply_all).toBe(true);
    expect(body.read_receipt_requested).toBe(true);
  });
});

describe("ticketed send (replyToClient)", () => {
  const ticketed = () => makeEmail({ ticket_id: "t1", draft_message: "Saved draft" });

  it("sends read_receipt_requested when ticked", async () => {
    const composer = await composerFor(ticketed());
    await composer().onSend({ ...SEND, readReceiptRequested: true });

    expect(replyToClient).toHaveBeenCalledTimes(1);
    expect(vi.mocked(replyToClient).mock.calls[0][1].read_receipt_requested).toBe(true);
  });

  it("an unticked ticketed send carries no flag", async () => {
    const composer = await composerFor(ticketed());
    await composer().onSend({ ...SEND, readReceiptRequested: false });

    expect("read_receipt_requested" in vi.mocked(replyToClient).mock.calls[0][1]).toBe(false);
  });
});

describe("saving drafts", () => {
  it("a pre-ticket draft save forwards the flag to the draft API", async () => {
    const onSaveDraft = vi.fn().mockResolvedValue(null);
    render(
      <MemoryRouter>
        <MessageDetailsView
          variant="panel"
          email={makeEmail({ draft_message: "Saved draft" })}
          folders={[]}
          onBack={vi.fn()}
          onRefreshList={vi.fn()}
          onRefreshMessage={vi.fn()}
          onForward={vi.fn()}
          onSaveDraft={onSaveDraft}
          onSendDraft={vi.fn()}
          onDiscardDraft={vi.fn()}
          onUploadDraftAttachment={vi.fn()}
          onRemoveDraftAttachment={vi.fn()}
          onUpdateTags={vi.fn()}
          onAssignFolder={vi.fn()}
          onMarkRead={vi.fn()}
          onMarkUnread={vi.fn()}
        />
      </MemoryRouter>
    );
    await screen.findByTestId("reply-composer");
    await composerProps.mock.calls.at(-1)![0].onSaveDraft("m", [], [], "<p>m</p>", true);

    expect(onSaveDraft).toHaveBeenCalledWith("i1", "m", [], [], "<p>m</p>", true);
  });

  it("a ticketed draft save stores the flag only when ticked", async () => {
    const composer = await composerFor(makeEmail({ ticket_id: "t1", draft_message: "Saved draft" }));

    await composer().onSaveDraft("m", [], [], "<p>m</p>", true);
    expect(vi.mocked(saveTicketReplyDraft).mock.calls.at(-1)![1].read_receipt_requested).toBe(true);

    await composer().onSaveDraft("m", [], [], "<p>m</p>", false);
    expect("read_receipt_requested" in vi.mocked(saveTicketReplyDraft).mock.calls.at(-1)![1]).toBe(false);
  });

  it("reopening a ticketed draft restores its saved checkbox state", async () => {
    vi.mocked((await import("@tw/api/interaction")).getTicketReplyDraft).mockResolvedValue({
      interaction_id: "d1",
      ticket_id: "t1",
      to_email: "client@example.com",
      to_emails: [],
      cc: [],
      bcc: [],
      message: "Saved",
      body_html: null,
      created_at: "2026-01-01T00:00:00Z",
      read_receipt_requested: true,
    });
    renderView(makeEmail({ ticket_id: "t1" }));
    await screen.findByTestId("reply-composer");

    await waitFor(() =>
      expect(composerProps.mock.calls.at(-1)![0].initialReadReceiptRequested).toBe(true)
    );
  });
});
