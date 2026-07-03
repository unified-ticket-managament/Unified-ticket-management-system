import { apiClient } from "./client";
import type { AgentSummary, InboxResponse, OpenEmailResponse } from "@tw/types";

// GET /agents
export async function listAgents(): Promise<AgentSummary[]> {
  const { data } = await apiClient.get<AgentSummary[]>("/agents");
  return data;
}

// GET /agents/me/inbox — the authenticated agent's own pending inbox.
export async function getAgentInbox(): Promise<InboxResponse> {
  const { data } = await apiClient.get<InboxResponse>("/agents/me/inbox");
  return data;
}

// GET /agents/me/inbox/{interaction_id}
export async function openEmail(interactionId: string): Promise<OpenEmailResponse> {
  const { data } = await apiClient.get<OpenEmailResponse>(
    `/agents/me/inbox/${interactionId}`
  );
  return data;
}
