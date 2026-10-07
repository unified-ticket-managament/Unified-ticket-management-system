import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TicketAssignmentsCard } from "@tw/components/ticket/TicketAssignmentsCard";
import type { AssignableAgentsResponse, TicketAssignmentsResponse } from "@tw/types";

// Assignments card -> Add Users. For a Team Lead, the Staff offered are
// narrowed to the same scoped lookup Create Ticket uses (own team + the
// ticket's categories); every other role keeps the transfer-candidates
// list unchanged. The backend (add_users) is the authority - these tests
// pin the picker side.

let currentUser: Record<string, unknown>;

vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast: vi.fn() }) }));
vi.mock("@tw/context/AuthContext", () => ({ useAuthContext: () => ({ currentUser }) }));
vi.mock("@tw/context/WorkflowContext", () => ({ useWorkflowContext: () => ({ allCategories: [] }) }));
// Render the offered users as plain text so assertions can read them.
vi.mock("@tw/components/common/UserMultiSelect", () => ({
  UserMultiSelect: ({ groups, roleOrder }: { groups: Record<string, { name: string }[]>; roleOrder: string[] }) => (
    <ul data-testid="offered">
      {roleOrder.flatMap((role) => groups[role].map((u) => <li key={role + u.name}>{`${role}:${u.name}`}</li>))}
    </ul>
  ),
}));

const api = vi.hoisted(() => ({
  getTicketAssignments: vi.fn(),
  assignTicketUsers: vi.fn(),
  updateTicketAssignment: vi.fn(),
  removeTicketAssignment: vi.fn(),
  addTicketCategory: vi.fn(),
  removeTicketCategory: vi.fn(),
}));
const getTransferCandidates = vi.hoisted(() => vi.fn());
const listAssignableAgents = vi.hoisted(() => vi.fn());
vi.mock("@tw/api/assignment", () => api);
vi.mock("@tw/api/ticket", () => ({ getTransferCandidates }));
vi.mock("@tw/api/agent", () => ({ listAssignableAgents }));

const u = (id: string, name: string) => ({ user_id: id, name, employee_number: null, is_on_leave: false });

// Wide, transfer-style candidate list (unchanged endpoint).
const TRANSFER_CANDIDATES: AssignableAgentsResponse = {
  me: u("tl", "Me TL"),
  groups: [
    { role: "Staff", users: [u("a", "Staff A"), u("b", "Staff B"), u("x", "Other Team Staff")] },
    { role: "Account Manager", users: [u("am", "Manager M")] },
  ],
};

function ticketState(): TicketAssignmentsResponse {
  return {
    ticket_id: "t1",
    ticket_status: "IN_PROGRESS",
    is_closed: false,
    closed_at: null,
    closed_by: null,
    assignments: [],
    categories: [
      { category_id: "c1", category_name: "AR", is_primary: true, assigned_at: "2026-10-06T10:00:00Z" },
      { category_id: "c2", category_name: "Quality", is_primary: false, assigned_at: "2026-10-06T10:00:00Z" },
    ],
  };
}

const scoped = (category?: string): AssignableAgentsResponse => ({
  me: u("tl", "Me TL"),
  groups: [
    {
      role: "Staff",
      users: category === "AR" ? [u("a", "Staff A")] : category === "Quality" ? [u("b", "Staff B")] : [],
    },
  ],
});

async function openAdd() {
  render(<TicketAssignmentsCard ticketId="t1" />);
  fireEvent.click(await screen.findByRole("button", { name: /Add Users/ }));
  return screen.findByTestId("offered");
}

const offered = () => Array.from(screen.getByTestId("offered").querySelectorAll("li")).map((li) => li.textContent);

beforeEach(() => {
  vi.clearAllMocks();
  api.getTicketAssignments.mockResolvedValue(ticketState());
  getTransferCandidates.mockResolvedValue(TRANSFER_CANDIDATES);
  listAssignableAgents.mockImplementation(async (category?: string) => scoped(category));
  currentUser = { user_id: "tl", role: "Team Lead", permissions: ["ticket:assign", "ticket:transfer"] };
});

describe("Assignments card - Add Users picker", () => {
  it("Team Lead: Staff are narrowed to the scoped lookup for EACH ticket category; other groups unchanged", async () => {
    await openAdd();
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalledTimes(2));
    expect(listAssignableAgents).toHaveBeenCalledWith("AR");
    expect(listAssignableAgents).toHaveBeenCalledWith("Quality");
    await waitFor(() => expect(offered()).toContain("Staff:Staff B"));
    expect(offered()).toEqual(
      expect.arrayContaining(["Me:Me TL", "Staff:Staff A", "Staff:Staff B", "Account Manager:Manager M"])
    );
    expect(offered()).not.toContain("Staff:Other Team Staff");
  });

  it("Team Lead: an unlinked team (no scoped Staff) is offered no Staff at all", async () => {
    listAssignableAgents.mockResolvedValue({ me: u("tl", "Me TL"), groups: [{ role: "Staff", users: [] }] });
    await openAdd();
    await waitFor(() => expect(listAssignableAgents).toHaveBeenCalled());
    await waitFor(() => expect(offered().some((t) => t?.startsWith("Staff:"))).toBe(false));
    expect(offered()).toContain("Account Manager:Manager M");
  });

  it("Team Lead: fails closed - if the scoped lookup errors, no Staff are offered", async () => {
    listAssignableAgents.mockRejectedValue(new Error("boom"));
    await openAdd();
    await waitFor(() => expect(offered().some((t) => t?.startsWith("Staff:"))).toBe(false));
    expect(offered()).toContain("Me:Me TL");
  });

  it.each(["Account Manager", "Site Lead", "Super Admin"])(
    "%s: the transfer-candidates list is used unchanged (no scoped lookup)",
    async (role) => {
      currentUser = { user_id: "x", role, permissions: ["ticket:assign", "ticket:transfer"] };
      await openAdd();
      await waitFor(() => expect(offered()).toContain("Staff:Other Team Staff"));
      expect(offered()).toEqual(expect.arrayContaining(["Staff:Staff A", "Staff:Staff B"]));
      expect(listAssignableAgents).not.toHaveBeenCalled();
    }
  );
});
