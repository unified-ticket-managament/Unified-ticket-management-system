import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import type { InteractionResponse, OpenEmailResponse } from "@tw/types";

// MessageDetailsView drags in most of the app (API modules, auth store,
// workflow context). Everything below is stubbed except the component
// under test: these tests only care about *where* the composer renders.
const composerMounts = vi.fn();
vi.mock("@tw/components/mail/ReplyComposer", () => ({
  ReplyComposer: ({ mode }: { mode: string }) => {
    composerMounts();
    return <div data-testid="reply-composer" data-mode={mode} />;
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
  authService: {
    me: vi.fn().mockResolvedValue({ permissions: ["communication:reply_external"] }),
  },
}));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ refreshUser: vi.fn() }),
}));
vi.mock("@tw/api/inbox", () => ({
  archiveInteraction: vi.fn(),
  replyToInteraction: vi.fn(),
  uploadDraftInlineImage: vi.fn(),
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

function renderView(variant: "panel" | "fullscreen" | "standalone", email = makeEmail()) {
  return render(
    <MemoryRouter>
      <MessageDetailsView
        variant={variant}
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

function precedes(a: Element, b: Element) {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

// A minimal REPLY-type interaction with distinguishable body text, for
// building multi-message threads. See MessageDetailsView.tsx's
// replyBubble() — payload.envelope is optional, so this bare shape is
// enough to render as its own bubble.
function makeReply(id: string, message: string, overrides: Partial<InteractionResponse> = {}): InteractionResponse {
  return {
    interaction_id: id,
    ticket_id: null,
    interaction_type: "REPLY",
    status: "ASSIGNED",
    direction: "OUTBOUND",
    performed_by: "u1",
    payload: { message },
    is_visible: true,
    removed_by: null,
    removed_at: null,
    message_id: null,
    created_at: "2026-01-01T11:00:00Z",
    ...overrides,
  } as InteractionResponse;
}

// A 3-message thread — the root plus two replies — used to verify the
// composer always mounts next to whichever bubble it targets.
function makeThreadedEmail(overrides: Partial<OpenEmailResponse> = {}): OpenEmailResponse {
  return makeEmail({
    body: "Message 1 body",
    replies: [makeReply("r1", "Message 2 body"), makeReply("r2", "Message 3 body")],
    ...overrides,
  });
}

// Each message (root or reply) renders inside a wrapper div keyed
// `mail-message-<interaction_id>` (see MessageDetailsView.tsx's
// selectedMessageId highlighting) — a stable handle for asserting
// where the composer landed relative to a specific message.
function messageWrapper(interactionId: string): HTMLElement {
  const element = document.getElementById(`mail-message-${interactionId}`);
  if (!element) throw new Error(`No message wrapper found for "${interactionId}"`);
  return element;
}

// The target bubble's own hover-reveal Reply/Reply All button, scoped
// to that one message so it's never ambiguous with the bottom
// toolbar's Reply/Reply All (which always targets the root bubble) or
// another message's own hover buttons.
function replyButtonIn(interactionId: string, label: "Reply" | "Reply All"): HTMLElement {
  return within(messageWrapper(interactionId)).getByRole("button", { name: label });
}

beforeEach(() => {
  composerMounts.mockClear();
  // jsdom doesn't implement these; the thread body uses them for measuring.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe("MessageDetailsView — Reply / Reply All composer placement", () => {
  it("no composer is mounted until a message's Reply/Reply All is activated", async () => {
    renderView("panel", makeThreadedEmail());
    expect(screen.queryByTestId("reply-composer")).not.toBeInTheDocument();
  });

  it.each(["Reply", "Reply All"] as const)(
    "activating %s on Message 1 renders the composer directly after Message 1, before Message 2",
    async (label) => {
      const user = userEvent.setup();
      renderView("panel", makeThreadedEmail());

      await user.click(replyButtonIn("i1", label));
      const composer = await screen.findByTestId("reply-composer");
      expect(composer).toHaveAttribute("data-mode", label === "Reply" ? "reply" : "replyAll");

      expect(precedes(messageWrapper("i1"), composer)).toBe(true);
      expect(precedes(composer, messageWrapper("r1"))).toBe(true);
      expect(precedes(composer, messageWrapper("r2"))).toBe(true);
    }
  );

  it.each(["Reply", "Reply All"] as const)(
    "activating %s on Message 2 renders the composer between Message 2 and Message 3",
    async (label) => {
      const user = userEvent.setup();
      renderView("panel", makeThreadedEmail());

      await user.click(replyButtonIn("r1", label));
      const composer = await screen.findByTestId("reply-composer");
      expect(composer).toHaveAttribute("data-mode", label === "Reply" ? "reply" : "replyAll");

      expect(precedes(messageWrapper("i1"), messageWrapper("r1"))).toBe(true);
      expect(precedes(messageWrapper("r1"), composer)).toBe(true);
      expect(precedes(composer, messageWrapper("r2"))).toBe(true);
    }
  );

  it.each(["Reply", "Reply All"] as const)(
    "activating %s on Message 3 renders the composer after Message 3, at the end of the thread",
    async (label) => {
      const user = userEvent.setup();
      renderView("panel", makeThreadedEmail());

      await user.click(replyButtonIn("r2", label));
      const composer = await screen.findByTestId("reply-composer");
      expect(composer).toHaveAttribute("data-mode", label === "Reply" ? "reply" : "replyAll");

      expect(precedes(messageWrapper("r1"), messageWrapper("r2"))).toBe(true);
      expect(precedes(messageWrapper("r2"), composer)).toBe(true);
    }
  );

  it("the composer never renders in the old fixed slot above the whole thread", async () => {
    const user = userEvent.setup();
    renderView("panel", makeThreadedEmail());

    await user.click(replyButtonIn("r1", "Reply"));
    const composer = await screen.findByTestId("reply-composer");

    const subject = screen.getByRole("heading", { name: "Printer is down" });
    const threadHeading = screen.getByRole("heading", { name: "Message" });
    // Sanity: the thread heading really does sit between the subject
    // and every message — if the composer were still pinned in the
    // old top slot, it would precede threadHeading instead.
    expect(precedes(subject, threadHeading)).toBe(true);
    expect(precedes(threadHeading, composer)).toBe(true);
    expect(precedes(composer, threadHeading)).toBe(false);
  });

  it("switching the targeted message moves the single composer instance rather than mounting a second one", async () => {
    const user = userEvent.setup();
    renderView("panel", makeThreadedEmail());

    await user.click(replyButtonIn("i1", "Reply"));
    await screen.findByTestId("reply-composer");
    expect(precedes(messageWrapper("i1"), screen.getByTestId("reply-composer"))).toBe(true);
    expect(precedes(screen.getByTestId("reply-composer"), messageWrapper("r1"))).toBe(true);

    await user.click(replyButtonIn("r2", "Reply"));
    await waitFor(() => {
      expect(precedes(messageWrapper("r2"), screen.getByTestId("reply-composer"))).toBe(true);
    });
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
  });

  it("a saved draft on the root message auto-opens the composer directly after the root message, not above the thread", async () => {
    renderView("panel", makeThreadedEmail({ draft_message: "work in progress" }));
    const composer = await screen.findByTestId("reply-composer");

    const threadHeading = screen.getByRole("heading", { name: "Message" });
    expect(precedes(threadHeading, composer)).toBe(true);
    expect(precedes(messageWrapper("i1"), composer)).toBe(true);
    expect(precedes(composer, messageWrapper("r1"))).toBe(true);
  });

  it("Reply then Reply All on the same message scroll the mounted composer into view without remounting", async () => {
    const scrollIntoView = vi.fn(function (this: Element) {
      // The target must already be in the DOM when we scroll to it.
      expect(this.querySelector('[data-testid="reply-composer"]')).not.toBeNull();
    });
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    renderView("panel", makeThreadedEmail());

    await user.click(replyButtonIn("r1", "Reply"));
    await screen.findByTestId("reply-composer");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    expect(scrollIntoView).toHaveBeenLastCalledWith(expect.objectContaining({ block: "nearest" }));
    expect(screen.getByTestId("reply-composer")).toHaveAttribute("data-mode", "reply");

    // Switching to Reply All on the SAME message re-scrolls without
    // remounting or relocating the composer.
    await user.click(replyButtonIn("r1", "Reply All"));
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
    expect(composerMounts.mock.calls.length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    expect(screen.getByTestId("reply-composer")).toHaveAttribute("data-mode", "replyAll");
    expect(precedes(messageWrapper("r1"), screen.getByTestId("reply-composer"))).toBe(true);
    expect(precedes(screen.getByTestId("reply-composer"), messageWrapper("r2"))).toBe(true);
  });

  it("clicking Reply again on the same message while its composer is already open still scrolls to it", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    renderView("panel", makeThreadedEmail());
    await user.click(replyButtonIn("i1", "Reply"));
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    await user.click(replyButtonIn("i1", "Reply"));
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
  });

  it("auto-opening a saved draft does not scroll", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    renderView("panel", makeEmail({ draft_message: "work in progress" }));
    await screen.findByTestId("reply-composer");
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("no composer is shown for a closed ticket", async () => {
    renderView("panel", makeEmail({ ticket_id: "t1", ticket_status: "CLOSED", draft_message: "x" }));
    expect(screen.queryByTestId("reply-composer")).not.toBeInTheDocument();
    expect(screen.getByText(/ticket is closed/i)).toBeInTheDocument();
  });
});

describe("MessageDetailsView — attachments sit between a message's header and its body", () => {
  const att = (id: string, filename: string, extra: object = {}) => ({
    id,
    filename,
    mime_type: "application/pdf",
    size: 1024,
    download_url: `/attachments/${id}`,
    ...extra,
  });

  it("shows each message's own attachments above that message's body, skipping inline images", () => {
    renderView(
      "panel",
      makeEmail({
        body: "First body text",
        attachments: [att("a1", "Report.pdf"), att("a2", "Invoice.xlsx"), att("a3", "logo.png", { is_inline: true })],
        replies: [
          {
            interaction_id: "r1",
            ticket_id: null,
            interaction_type: "REPLY",
            status: "ASSIGNED",
            direction: "OUTBOUND",
            performed_by: "u1",
            payload: { message: "Second body text" },
            is_visible: true,
            removed_by: null,
            removed_at: null,
            message_id: null,
            created_at: "2026-01-01T11:00:00Z",
            attachments: [att("a4", "Reply.pdf")],
          } as never,
        ],
      })
    );

    const body1 = screen.getByText("First body text");
    const report = screen.getByRole("button", { name: /Report\.pdf/ });
    const invoice = screen.getByRole("button", { name: /Invoice\.xlsx/ });
    const body2 = screen.getByText("Second body text");
    const replyAtt = screen.getByRole("button", { name: /Reply\.pdf/ });

    // Message 1: its attachments precede its body, and sit together.
    expect(precedes(report, body1)).toBe(true);
    expect(precedes(invoice, body1)).toBe(true);
    expect(report.parentElement).toBe(invoice.parentElement);
    // Message 2's attachment stays with message 2, not hoisted to message 1.
    expect(precedes(body1, replyAtt)).toBe(true);
    expect(precedes(replyAtt, body2)).toBe(true);
    // Inline (signature/CID) images are not listed as attachments.
    expect(screen.queryByRole("button", { name: /logo\.png/ })).not.toBeInTheDocument();
  });

  it("renders no attachment section when a message has none", () => {
    renderView("panel", makeEmail({ attachments: [] }));
    expect(screen.queryByRole("button", { name: /\.pdf/ })).not.toBeInTheDocument();
  });
});
