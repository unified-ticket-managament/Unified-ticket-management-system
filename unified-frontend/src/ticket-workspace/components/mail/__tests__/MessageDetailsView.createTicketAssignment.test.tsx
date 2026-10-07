import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import type { AssignableAgentsResponse, OpenEmailResponse } from "@tw/types";

// Create Ticket dialog - "Assigned To -> Staff" picker as a Team Lead.
// The backend is the authority on who is in scope (see
// unified-backend/tests/test_team_lead_assignable_staff.py); these tests
// pin the dialog's side: it asks for the staff of the SELECTED category,
// shows exactly what comes back, never shows the "no staff" message when
// staff exist, and drops a stale assignee when the category changes.

const listAssignableAgents = vi.fn();
const createTicketFromInteraction = vi.fn();
const permissions = { current: ["ticket:create", "ticket:assign", "communication:reply_external"] };

vi.mock("@tw/components/mail/ReplyComposer", () => ({ ReplyComposer: () => null }));
vi.mock("@tw/components/sla/SlaFirstResponseBadge", () => ({ SlaFirstResponseBadge: () => null }));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({
    setSelectedEmail: vi.fn(),
    allCategories: [
      { category_id: "c1", category_name: "AR" },
      { category_id: "c2", category_name: "Denials" },
      { category_id: "c3", category_name: "Empty" },
    ],
    allCategoriesLoading: false,
    allCategoriesError: false,
  }),
}));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: { user_id: "tl1", signature_html: null, permissions: permissions.current },
  }),
}));
vi.mock("@/services", () => ({
  authService: { me: vi.fn().mockResolvedValue({ permissions: [] }) },
}));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ refreshUser: vi.fn() }),
}));
vi.mock("@tw/api/inbox", () => ({
  archiveInteraction: vi.fn(),
  replyToInteraction: vi.fn(),
  uploadDraftInlineImage: vi.fn(),
}));
vi.mock("@tw/api/agent", () => ({
  listAssignableAgents: (category?: string) => listAssignableAgents(category),
}));
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
  createTicketFromInteraction: (...a: unknown[]) => createTicketFromInteraction(...a),
  listTickets: vi.fn().mockResolvedValue([]),
}));

const user = (id: string, name: string) => ({
  user_id: id,
  name,
  employee_number: null,
  is_on_leave: false,
});

// What the (already RBAC- and category-scoped) backend would return for TL1.
function agentsFor(category?: string): AssignableAgentsResponse {
  const staff =
    category === "AR"
      ? [user("a", "Staff A"), user("b", "Staff B"), user("c", "Staff C")]
      : category === "Denials"
        ? [user("d", "Staff D"), user("e", "Staff E")]
        : category === "Empty"
          ? []
          : [user("a", "Staff A"), user("d", "Staff D")];
  return { me: user("tl1", "Team Lead One"), groups: [{ role: "Staff", users: staff }] };
}

function makeEmail(): OpenEmailResponse {
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
    body: "Hello",
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
  } as OpenEmailResponse;
}

function renderView() {
  return render(
    <MemoryRouter>
      <MessageDetailsView
        variant="panel"
        email={makeEmail()}
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

const NO_STAFF = "No Staff found in your reporting hierarchy.";

async function openDialog() {
  const u = userEvent.setup();
  renderView();
  await u.click(screen.getAllByRole("button", { name: "Create Ticket" })[0]);
  const dialog = await screen.findByRole("dialog");
  return { u, dialog };
}

// Radix selects, in DOM order: Category, Priority, Assigned To, [Staff].
async function choose(u: ReturnType<typeof userEvent.setup>, dialog: HTMLElement, index: number, option: string) {
  await u.click(within(dialog).getAllByRole("combobox")[index]);
  await u.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  listAssignableAgents.mockReset().mockImplementation(async (category?: string) => agentsFor(category));
  createTicketFromInteraction.mockReset().mockResolvedValue({ ticket_id: "t1" });
  permissions.current = ["ticket:create", "ticket:assign", "communication:reply_external"];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  // jsdom gaps Radix Select relies on.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});

describe("Create Ticket dialog - Team Lead staff assignment", () => {
  it("selecting a category requests that category's staff and lists them", async () => {
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("AR"));

    await choose(u, dialog, 2, "Staff");
    await u.click(within(dialog).getAllByRole("combobox")[3]);
    const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(names).toEqual(["Staff A", "Staff B", "Staff C"]);
    expect(within(dialog).queryByText(NO_STAFF)).toBeNull();
  });

  it("changing category refreshes the options to the new category's staff", async () => {
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("AR"));
    await choose(u, dialog, 0, "Denials");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("Denials"));

    await choose(u, dialog, 2, "Staff");
    await u.click(within(dialog).getAllByRole("combobox")[3]);
    const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(names).toEqual(["Staff D", "Staff E"]);
  });

  it("clears an assignee picked under the previous category when the category changes", async () => {
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("AR"));
    await choose(u, dialog, 2, "Staff");
    await choose(u, dialog, 3, "Staff B");
    expect(within(dialog).getAllByRole("combobox")[3]).toHaveTextContent("Staff B");

    await choose(u, dialog, 0, "Denials");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("Denials"));
    // Back to "Unassigned (Team)": no staff picker, so no stale AR assignee.
    await waitFor(() => expect(within(dialog).getAllByRole("combobox")).toHaveLength(3));
    expect(within(dialog).getAllByRole("combobox")[2]).toHaveTextContent("Unassigned (Team)");
    expect(within(dialog).queryByText("Staff B")).toBeNull();
    await u.click(within(dialog).getByRole("button", { name: "Create Ticket" }));
    await waitFor(() => expect(createTicketFromInteraction).toHaveBeenCalled());
    expect(createTicketFromInteraction.mock.calls[0][0]).toMatchObject({
      ticket_type: "Denials",
      agent_id: undefined,
    });
  });

  it("shows the empty-state message only when the category genuinely has no staff, and blocks Create", async () => {
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "Empty");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("Empty"));
    await choose(u, dialog, 2, "Staff");
    expect(await within(dialog).findByText(NO_STAFF)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create Ticket" })).toBeDisabled();
  });

  it("creates the ticket with the chosen in-category staff member as agent_id", async () => {
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await waitFor(() => expect(listAssignableAgents).toHaveBeenLastCalledWith("AR"));
    await choose(u, dialog, 2, "Staff");
    const create = within(dialog).getByRole("button", { name: "Create Ticket" });
    expect(create).toBeDisabled(); // staff group chosen but nobody picked yet
    await choose(u, dialog, 3, "Staff C");
    expect(create).toBeEnabled();
    await u.click(create);

    await waitFor(() => expect(createTicketFromInteraction).toHaveBeenCalledTimes(1));
    expect(createTicketFromInteraction.mock.calls[0][0]).toMatchObject({
      interaction_id: "i1",
      ticket_type: "AR",
      agent_id: "c",
    });
  });

  it("a slow response for a previous category never overwrites the current category's list", async () => {
    const resolvers: Record<string, (v: AssignableAgentsResponse) => void> = {};
    listAssignableAgents.mockImplementation(
      (category?: string) =>
        new Promise<AssignableAgentsResponse>((resolve) => {
          resolvers[category ?? ""] = resolve;
        })
    );
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await choose(u, dialog, 0, "Denials");
    await waitFor(() => expect(resolvers.Denials).toBeDefined());
    resolvers.Denials(agentsFor("Denials"));
    resolvers.AR(agentsFor("AR")); // arrives late

    await choose(u, dialog, 2, "Staff");
    await u.click(within(dialog).getAllByRole("combobox")[3]);
    const names = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(names).toEqual(["Staff D", "Staff E"]);
  });

  it("a Staff user (no groups) still only gets themselves - unchanged for other roles", async () => {
    listAssignableAgents.mockResolvedValue({ me: user("tl1", "Team Lead One"), groups: [] });
    permissions.current = ["ticket:create", "communication:reply_external"];
    const { u, dialog } = await openDialog();
    await choose(u, dialog, 0, "AR");
    await u.click(within(dialog).getAllByRole("combobox")[2]);
    const options = (await screen.findAllByRole("option")).map((o) => o.textContent);
    expect(options).toEqual(["Unassigned (Team)", "Myself (Team Lead One)"]);
  });
});
