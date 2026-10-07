import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMailFeatures, replyToInteraction } from "@tw/api/inbox";
import { replyToClient, saveTicketReplyDraft } from "@tw/api/interaction";
import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import { resetMailFeaturesCacheForTests } from "@tw/hooks/useMailFeatures";
import type { InteractionResponse, OpenEmailResponse, ReadReceiptStatus } from "@tw/types";

// Thread display order in the reading pane: newest reply first, original
// message last. The API order (oldest first) is untouched.

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

beforeEach(() => {
  composerProps.mockClear();
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

function msg(id: string, body: string, created_at: string, overrides: Partial<InteractionResponse> = {}) {
  return reply(id, { created_at, payload: { message: body, envelope: { from_name: "Agent" } }, ...overrides });
}

function positions(...bodies: string[]) {
  const text = document.body.textContent ?? "";
  return bodies.map((b) => text.indexOf(b));
}

describe("thread display order", () => {
  it("one-message thread renders just the original message", () => {
    renderView(makeEmail({ body: "ORIGINAL", replies: [] }));
    expect(screen.getByText("ORIGINAL")).toBeInTheDocument();
  });

  it("two-message thread shows the latest reply above the original", () => {
    renderView(makeEmail({ body: "ORIGINAL", replies: [msg("r1", "REPLY1", "2026-01-01T11:00:00Z")] }));
    const [reply1, original] = positions("REPLY1", "ORIGINAL");
    expect(reply1).toBeGreaterThan(-1);
    expect(reply1).toBeLessThan(original);
  });

  it("long mixed inbound/outbound thread is strictly newest to oldest, original last", () => {
    const inbound = (id: string, body: string, created_at: string) =>
      reply(id, {
        interaction_type: "EMAIL",
        direction: "INBOUND",
        created_at,
        payload: { body, from_name: "Client", from_email: "client@example.com" },
      });
    renderView(
      makeEmail({
        body: "ORIGINAL",
        // API order: oldest first.
        replies: [
          msg("r1", "STAFF-11AM", "2026-01-01T11:00:00Z"),
          inbound("r2", "CLIENT-12PM", "2026-01-01T12:00:00Z"),
          msg("r3", "STAFF-1PM", "2026-01-01T13:00:00Z"),
        ],
      })
    );
    const pos = positions("STAFF-1PM", "CLIENT-12PM", "STAFF-11AM", "ORIGINAL");
    expect(pos.every((p) => p > -1)).toBe(true);
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
  });

  it("forward rows stay in the sequence by time", () => {
    renderView(
      makeEmail({
        body: "ORIGINAL",
        replies: [
          msg("r1", "FIRST", "2026-01-01T11:00:00Z"),
          reply("f1", {
            interaction_type: "FORWARD",
            created_at: "2026-01-01T12:00:00Z",
            payload: { envelope: { from_name: "FWDACTOR" }, recipients: [] },
          }),
        ],
      })
    );
    const pos = positions("FWDACTOR", "FIRST", "ORIGINAL");
    expect(pos.every((p) => p > -1)).toBe(true);
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
  });

  it("attachments stay with their own message", () => {
    const att = (name: string) => [
      { attachment_id: name, filename: name, content_type: "text/plain", size_bytes: 1, download_url: "x" },
    ];
    renderView(
      makeEmail({
        body: "ORIGINAL",
        attachments: att("root.txt") as never,
        replies: [msg("r1", "REPLY1", "2026-01-01T11:00:00Z", { attachments: att("reply.txt") as never })],
      })
    );
    const [replyBody, replyFile, rootBody, rootFile] = positions("REPLY1", "reply.txt", "ORIGINAL", "root.txt");
    // Each message lists its attachments just above its own body, and the
    // reply's block sits above the original's.
    expect(replyFile).toBeLessThan(replyBody);
    expect(replyBody).toBeLessThan(rootFile);
    expect(rootFile).toBeLessThan(rootBody);
  });
});
