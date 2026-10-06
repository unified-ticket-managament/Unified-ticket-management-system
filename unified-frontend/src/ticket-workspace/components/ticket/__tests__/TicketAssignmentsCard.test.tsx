import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  TicketAssignmentsCard,
  describeAssignmentSla,
} from "@tw/components/ticket/TicketAssignmentsCard";
import type { AssignmentSLARunState, TicketAssignmentsResponse } from "@tw/types";

const pushToast = vi.fn();
let currentUser: Record<string, unknown>;

vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));
vi.mock("@tw/context/AuthContext", () => ({ useAuthContext: () => ({ currentUser }) }));
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({
    allCategories: [
      { category_id: "cat-billing", category_name: "Medical Billing", inbox_email: null },
      { category_id: "cat-claims", category_name: "Claims", inbox_email: null },
      { category_id: "cat-denials", category_name: "Denials", inbox_email: null },
    ],
  }),
}));
vi.mock("@tw/components/common/UserMultiSelect", () => ({ UserMultiSelect: () => null }));

const api = vi.hoisted(() => ({
  getTicketAssignments: vi.fn(),
  assignTicketUsers: vi.fn(),
  updateTicketAssignment: vi.fn(),
  removeTicketAssignment: vi.fn(),
  addTicketCategory: vi.fn(),
  removeTicketCategory: vi.fn(),
}));
vi.mock("@tw/api/assignment", () => api);
vi.mock("@tw/api/ticket", () => ({
  getTransferCandidates: vi.fn().mockResolvedValue({ me: null, groups: [] }),
}));

function run(overrides: Partial<AssignmentSLARunState> = {}): AssignmentSLARunState {
  return {
    assignment_sla_id: "run",
    run_number: 1,
    priority: "MEDIUM",
    status: "RUNNING",
    started_at: "2026-10-06T10:00:00Z",
    due_at: "2026-10-06T13:00:00Z",
    active_target_minutes: 180,
    paused_at: null,
    total_paused_seconds: 0,
    completed_at: null,
    completion_reason: null,
    breached: false,
    breached_at: null,
    remaining_seconds: 3 * 3600,
    elapsed_fraction: 0.1,
    ...overrides,
  };
}

function state(overrides: Partial<TicketAssignmentsResponse> = {}): TicketAssignmentsResponse {
  return {
    ticket_id: "t1",
    ticket_status: "IN_PROGRESS",
    is_closed: false,
    closed_at: null,
    closed_by: null,
    assignments: [
      {
        assignment_id: "a-koushik",
        user_id: "u-koushik",
        user_name: "Koushik",
        is_primary: true,
        status: "IN_PROGRESS",
        assigned_by: null,
        assigned_by_name: null,
        assigned_at: "2026-10-06T10:00:00Z",
        status_changed_at: null,
        closed_at: null,
        resolution_sla: run({ remaining_seconds: 3 * 3600 }),
        sla_history: [],
      },
      {
        assignment_id: "a-ravi",
        user_id: "u-ravi",
        user_name: "Ravi",
        is_primary: false,
        status: "PENDING",
        assigned_by: null,
        assigned_by_name: null,
        assigned_at: "2026-10-06T10:00:00Z",
        status_changed_at: null,
        closed_at: null,
        resolution_sla: run({ remaining_seconds: 2 * 3600 }),
        sla_history: [],
      },
      {
        assignment_id: "a-suresh",
        user_id: "u-suresh",
        user_name: "Suresh",
        is_primary: false,
        status: "RESOLVED",
        assigned_by: null,
        assigned_by_name: null,
        assigned_at: "2026-10-06T10:00:00Z",
        status_changed_at: null,
        closed_at: null,
        resolution_sla: run({ status: "COMPLETED", remaining_seconds: null, completed_at: "2026-10-06T11:00:00Z" }),
        sla_history: [],
      },
    ],
    categories: [
      { category_id: "cat-billing", category_name: "Medical Billing", is_primary: true, assigned_at: "2026-10-06T10:00:00Z" },
      { category_id: "cat-claims", category_name: "Claims", is_primary: false, assigned_at: "2026-10-06T10:00:00Z" },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  currentUser = {
    user_id: "u-ravi",
    role: "Staff",
    permissions: ["ticket:update_status", "ticket:editown_ticket"],
  };
  api.getTicketAssignments.mockResolvedValue(state());
});

describe("describeAssignmentSla", () => {
  it("shows remaining time for a running run", () => {
    expect(describeAssignmentSla(run({ remaining_seconds: 3 * 3600 + 600 })).label).toBe("3h 10m remaining");
  });
  it("shows Completed / Breached / Paused distinctly", () => {
    expect(describeAssignmentSla(run({ status: "COMPLETED", remaining_seconds: null })).label).toBe("Completed");
    expect(describeAssignmentSla(run({ breached: true })).label).toBe("Breached");
    expect(describeAssignmentSla(run({ status: "PAUSED", remaining_seconds: 720 })).label).toBe("Paused · 12m left");
  });
  it("handles a missing run", () => {
    expect(describeAssignmentSla(null).label).toBe("No SLA");
  });
});

describe("TicketAssignmentsCard", () => {
  it("lists every assignee with primary/secondary, own status and own SLA", async () => {
    render(<TicketAssignmentsCard ticketId="t1" />);
    const koushik = await screen.findByTestId("assignment-row-u-koushik");
    expect(within(koushik).getByText("Primary")).toBeInTheDocument();
    expect(within(koushik).getByText("In Progress")).toBeInTheDocument();
    expect(within(koushik).getByText("3h 0m remaining")).toBeInTheDocument();

    const suresh = screen.getByTestId("assignment-row-u-suresh");
    expect(within(suresh).getByText("Secondary")).toBeInTheDocument();
    expect(within(suresh).getByText("Resolved")).toBeInTheDocument();
    expect(within(suresh).getByText("Completed")).toBeInTheDocument();

    expect(screen.getByTestId("category-chip-Medical Billing")).toBeInTheDocument();
    expect(screen.getByTestId("category-chip-Claims")).toBeInTheDocument();
  });

  it("a secondary assignee can change ONLY their own status (not read-only)", async () => {
    api.updateTicketAssignment.mockResolvedValue(state());
    render(<TicketAssignmentsCard ticketId="t1" />);
    await screen.findByTestId("assignment-row-u-ravi");

    const ownSelect = screen.getByLabelText("Status for Ravi");
    expect(screen.queryByLabelText("Status for Koushik")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Status for Suresh")).not.toBeInTheDocument();

    fireEvent.change(ownSelect, { target: { value: "IN_PROGRESS" } });
    await waitFor(() =>
      expect(api.updateTicketAssignment).toHaveBeenCalledWith("t1", "a-ravi", { status: "IN_PROGRESS" })
    );
  });

  it("hides assignment-management controls the user's RBAC doesn't allow", async () => {
    render(<TicketAssignmentsCard ticketId="t1" />);
    await screen.findByTestId("assignment-row-u-ravi");
    expect(screen.queryByRole("button", { name: /Add Users/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Make Primary/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Category to add")).not.toBeInTheDocument();
  });

  it("a supervisor can promote a secondary to primary", async () => {
    currentUser = {
      user_id: "u-tl",
      role: "Team Lead",
      permissions: ["ticket:assign", "ticket:transfer", "ticket:update_status"],
    };
    api.updateTicketAssignment.mockResolvedValue(state());
    render(<TicketAssignmentsCard ticketId="t1" />);
    const ravi = await screen.findByTestId("assignment-row-u-ravi");
    fireEvent.click(within(ravi).getByRole("button", { name: "Make Primary" }));
    await waitFor(() =>
      expect(api.updateTicketAssignment).toHaveBeenCalledWith("t1", "a-ravi", { is_primary: true })
    );
  });

  it("removing the primary requires choosing a new primary first", async () => {
    currentUser = { user_id: "u-tl", role: "Team Lead", permissions: ["ticket:transfer"] };
    api.removeTicketAssignment.mockResolvedValue(state());
    render(<TicketAssignmentsCard ticketId="t1" />);
    const koushik = await screen.findByTestId("assignment-row-u-koushik");
    fireEvent.click(within(koushik).getByRole("button", { name: "Remove Koushik" }));

    const dialogRemove = screen.getAllByRole("button", { name: "Remove" }).at(-1)!;
    expect(dialogRemove).toBeDisabled();
    // SelectInput renders its label without a for= association, so find it by value.
    fireEvent.change(screen.getByDisplayValue("Select…"), { target: { value: "a-ravi" } });
    expect(dialogRemove).not.toBeDisabled();
    fireEvent.click(dialogRemove);
    await waitFor(() =>
      expect(api.removeTicketAssignment).toHaveBeenCalledWith("t1", "a-koushik", "a-ravi")
    );
  });

  it("adds a category the ticket doesn't have yet", async () => {
    currentUser = { user_id: "u-am", role: "Account Manager", permissions: ["ticket:change_category"] };
    api.addTicketCategory.mockResolvedValue(state());
    render(<TicketAssignmentsCard ticketId="t1" />);
    await screen.findByTestId("category-chip-Claims");
    const select = screen.getByLabelText("Category to add") as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.textContent);
    expect(options).toContain("Denials");
    expect(options).not.toContain("Claims");
    fireEvent.change(select, { target: { value: "cat-denials" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.addTicketCategory).toHaveBeenCalledWith("t1", "cat-denials"));
  });

  it("a closed ticket shows every assignment as closed and offers no edits", async () => {
    currentUser = { user_id: "u-tl", role: "Team Lead", permissions: ["ticket:assign", "ticket:transfer"] };
    const closed = state({ is_closed: true, ticket_status: "CLOSED" });
    closed.assignments = closed.assignments.map((a) => ({ ...a, status: "CLOSED" }));
    api.getTicketAssignments.mockResolvedValue(closed);
    render(<TicketAssignmentsCard ticketId="t1" />);
    expect(await screen.findByText(/Ticket is closed/)).toBeInTheDocument();
    expect(screen.getAllByText("Closed")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Add Users/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Make Primary/ })).not.toBeInTheDocument();
  });
});
