import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MailReminder } from "@tw/api/mailReminders";
import { MailReminderProvider } from "@tw/components/mail/MailReminderContext";
import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import type { InteractionResponse, OpenEmailResponse } from "@tw/types";

// "Remind me" inside the real reading pane (R-038 R-041 R-043): the toolbar
// button, the header chip and the due banner — and that opening the view
// without a reminder provider (other screens) shows none of it and breaks
// nothing.

const reminderApi = vi.hoisted(() => ({
  getReminders: vi.fn(),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  cancelReminder: vi.fn(),
  snoozeReminder: vi.fn(),
  dismissReminder: vi.fn(),
}));
vi.mock("@tw/api/mailReminders", () => reminderApi);

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
const pushToast = vi.hoisted(() => vi.fn());
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));
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

function renderView(email: OpenEmailResponse, variant: "panel" | "fullscreen" = "panel", withProvider = true) {
  const view = (
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
  );
  return render(
    <MemoryRouter>
      {withProvider ? <MailReminderProvider>{view}</MailReminderProvider> : view}
    </MemoryRouter>
  );
}


const DAY = 24 * 60 * 60_000;
function reminder(over: Partial<MailReminder> = {}): MailReminder {
  return {
    reminder_id: "r1",
    interaction_id: "i1",
    remind_at: new Date(Date.now() + DAY).toISOString(),
    status: "ACTIVE",
    snooze_count: 0,
    fired_at: null,
    completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...over,
  };
}
let server: MailReminder[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  server = [];
  reminderApi.getReminders.mockImplementation(async (p?: { status?: string }) =>
    server.filter((r) => !p?.status || r.status === p.status)
  );
  reminderApi.createReminder.mockImplementation(async (interactionId: string, at: Date) => {
    const r = reminder({ reminder_id: "new1", interaction_id: interactionId, remind_at: at.toISOString() });
    server.push(r);
    return r;
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe("reading pane reminders", () => {
  it.each(["panel", "fullscreen"] as const)(
    "shows a Remind me button in the %s toolbar, next to Mark as Unread",
    async (variant) => {
      renderView(makeEmail(), variant);

      expect(await screen.findByRole("button", { name: "Remind me" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Mark as Unread" })).toBeInTheDocument();
    }
  );

  it("Remind me → Tomorrow → Set reminder creates it for THIS email", async () => {
    const user = userEvent.setup();
    renderView(makeEmail({ interaction_id: "i1" }));

    await user.click(await screen.findByRole("button", { name: "Remind me" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-tomorrow"));
    await user.click(within(dialog).getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(reminderApi.createReminder).toHaveBeenCalledTimes(1));
    expect(reminderApi.createReminder.mock.calls[0][0]).toBe("i1");
    // the header chip appears and the toolbar button switches to Edit
    expect(await screen.findByTestId("reminder-chip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit reminder" })).toBeInTheDocument();
  });

  it("shows the existing reminder in the header", async () => {
    server = [reminder()];
    renderView(makeEmail());

    expect(await screen.findByTestId("reminder-chip")).toHaveTextContent("Reminder:");
  });

  it("shows the 'Reminder due' banner with Snooze and Dismiss for a fired reminder", async () => {
    server = [reminder({ status: "FIRED" })];
    renderView(makeEmail());

    const banner = await screen.findByTestId("reminder-due-banner");
    expect(within(banner).getByRole("button", { name: "Snooze" })).toBeInTheDocument();
    expect(within(banner).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("another email's reminder is not shown on this one", async () => {
    server = [reminder({ interaction_id: "someone-else" })];
    renderView(makeEmail({ interaction_id: "i1" }));

    await waitFor(() => expect(reminderApi.getReminders).toHaveBeenCalled());
    expect(screen.queryByTestId("reminder-chip")).toBeNull();
    expect(screen.getByRole("button", { name: "Remind me" })).toBeInTheDocument();
  });

  it("without a reminder provider the view has no reminder UI and still works", async () => {
    renderView(makeEmail(), "panel", false);

    expect(await screen.findByRole("button", { name: "Mark as Unread" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remind/i })).toBeNull();
    expect(screen.queryByTestId("reminder-chip")).toBeNull();
    expect(reminderApi.getReminders).not.toHaveBeenCalled();
  });

  it("existing toolbar actions are still present (regression)", async () => {
    renderView(makeEmail());

    // The threading UI renders Reply / Reply All / Forward on every message,
    // so these names can match several buttons — assert at least one exists.
    for (const name of ["Reply", "Reply All", "Forward", "Archive", "Mark as Unread"]) {
      expect((await screen.findAllByRole("button", { name })).length).toBeGreaterThan(0);
    }
  });
});
