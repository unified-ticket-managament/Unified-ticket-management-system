import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import type { OpenEmailResponse } from "@tw/types";

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
  it.each(["panel", "fullscreen"] as const)(
    "%s: Reply opens the composer under the header and above the thread",
    async (variant) => {
      const user = userEvent.setup();
      renderView(variant);
      expect(screen.queryByTestId("reply-composer")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /^reply$/i }));
      const composer = await screen.findByTestId("reply-composer");
      expect(composer).toHaveAttribute("data-mode", "reply");

      const subject = screen.getByRole("heading", { name: "Printer is down" });
      const threadHeading = screen.getByRole("heading", { name: "Message" });
      expect(precedes(subject, composer)).toBe(true);
      expect(precedes(composer, threadHeading)).toBe(true);
    }
  );

  it.each(["panel", "fullscreen"] as const)("%s: Reply All opens the composer in the same top slot", async (variant) => {
    const user = userEvent.setup();
    renderView(variant);
    await user.click(screen.getByRole("button", { name: /reply all/i }));
    const composer = await screen.findByTestId("reply-composer");
    expect(composer).toHaveAttribute("data-mode", "replyAll");
    expect(precedes(composer, screen.getByRole("heading", { name: "Message" }))).toBe(true);
  });

  it("a saved draft still auto-opens the composer, now at the top", async () => {
    renderView("panel", makeEmail({ draft_message: "work in progress" }));
    const composer = await screen.findByTestId("reply-composer");
    expect(precedes(composer, screen.getByRole("heading", { name: "Message" }))).toBe(true);
  });

  it("renders exactly one composer", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    const user = userEvent.setup();
    renderView("fullscreen");
    await user.click(screen.getByRole("button", { name: /^reply$/i }));
    await waitFor(() => expect(screen.getAllByTestId("reply-composer")).toHaveLength(1));
  });

  it.each(["panel", "fullscreen"] as const)(
    "%s: Reply and Reply All scroll the mounted composer into view",
    async (variant) => {
      const scrollIntoView = vi.fn(function (this: Element) {
        // The target must already be in the DOM when we scroll to it.
        expect(this.querySelector('[data-testid="reply-composer"]')).not.toBeNull();
      });
      Element.prototype.scrollIntoView = scrollIntoView;
      const user = userEvent.setup();
      renderView(variant);

      await user.click(screen.getByRole("button", { name: /^reply$/i }));
      await screen.findByTestId("reply-composer");
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
      expect(scrollIntoView).toHaveBeenLastCalledWith(expect.objectContaining({ block: "nearest" }));

      // Switching to Reply All re-scrolls without remounting the composer.
      await user.click(screen.getByRole("button", { name: /reply all/i }));
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(2));
      expect(composerMounts.mock.calls.length).toBeGreaterThan(0);
      expect(screen.getAllByTestId("reply-composer")).toHaveLength(1);
    }
  );

  it("clicking Reply again while the composer is already open still scrolls to it", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    renderView("panel");
    await user.click(screen.getByRole("button", { name: /^reply$/i }));
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: /^reply$/i }));
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
