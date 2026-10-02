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

  it("renders exactly one composer, and does so by layout order rather than scrolling", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const user = userEvent.setup();
    renderView("fullscreen");
    await user.click(screen.getByRole("button", { name: /^reply$/i }));
    await waitFor(() => expect(screen.getAllByTestId("reply-composer")).toHaveLength(1));
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("no composer is shown for a closed ticket", async () => {
    renderView("panel", makeEmail({ ticket_id: "t1", ticket_status: "CLOSED", draft_message: "x" }));
    expect(screen.queryByTestId("reply-composer")).not.toBeInTheDocument();
    expect(screen.getByText(/ticket is closed/i)).toBeInTheDocument();
  });
});
