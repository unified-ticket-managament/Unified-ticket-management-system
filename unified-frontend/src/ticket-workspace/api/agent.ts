import { apiClient } from "./client";
import type { AgentSummary } from "@tw/types";

// GET /agents — omit `category` for every active Staff member;
// pass a ticket's `ticket_type` to scope results to that one
// work-specialization category (the Assign-to-Staff picker).
export async function listAgents(category?: string): Promise<AgentSummary[]> {
  const { data } = await apiClient.get<AgentSummary[]>("/agents", {
    params: category ? { category } : undefined,
  });
  return data;
}
