import { apiClient } from "./client";
import type { AgentSummary } from "@tw/types";

// GET /agents
export async function listAgents(): Promise<AgentSummary[]> {
  const { data } = await apiClient.get<AgentSummary[]>("/agents");
  return data;
}
