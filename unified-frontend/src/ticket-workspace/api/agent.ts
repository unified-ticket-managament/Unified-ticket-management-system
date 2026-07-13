import { apiClient } from "./client";
import type { AgentSummary, AssignableAgentsResponse } from "@tw/types";

// GET /agents — omit `category` for every active Staff member;
// pass a ticket's `ticket_type` to scope results to that one
// work-specialization category (the Assign-to-Staff picker).
export async function listAgents(category?: string): Promise<AgentSummary[]> {
  const { data } = await apiClient.get<AgentSummary[]>("/agents", {
    params: category ? { category } : undefined,
  });
  return data;
}

// GET /agents/assignable — who the current user may assign a
// brand-new ticket to on the Create Ticket dialog, scoped per their
// own role/hierarchy (see AssignmentService on the backend).
export async function listAssignableAgents(): Promise<AssignableAgentsResponse> {
  const { data } = await apiClient.get<AssignableAgentsResponse>("/agents/assignable");
  return data;
}
