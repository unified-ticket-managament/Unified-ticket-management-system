import { apiClient } from "./client";
import type {
  AttachInteractionRequest,
  AttachInteractionResponse,
  TicketActionResponse,
  TicketFromInteractionRequest,
  TicketFromInteractionResponse,
  TicketResponse,
  TicketUpdateRequest,
  TransferAgentRequest,
} from "@/types";

// GET /tickets?agent_name=...
export async function listTickets(agentName?: string): Promise<TicketResponse[]> {
  const { data } = await apiClient.get<TicketResponse[]>("/tickets", {
    params: agentName ? { agent_name: agentName } : undefined,
  });
  return data;
}

// POST /tickets/from-interaction
export async function createTicketFromInteraction(
  payload: TicketFromInteractionRequest
): Promise<TicketFromInteractionResponse> {
  const { data } = await apiClient.post<TicketFromInteractionResponse>(
    "/tickets/from-interaction",
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/attach-interaction
export async function attachInteractionToTicket(
  ticketId: string,
  payload: AttachInteractionRequest
): Promise<AttachInteractionResponse> {
  const { data } = await apiClient.post<AttachInteractionResponse>(
    `/tickets/${ticketId}/attach-interaction`,
    payload
  );
  return data;
}

// GET /tickets/{ticket_id}?agent_name=...
export async function getTicket(
  ticketId: string,
  agentName?: string
): Promise<TicketResponse> {
  const { data } = await apiClient.get<TicketResponse>(`/tickets/${ticketId}`, {
    params: agentName ? { agent_name: agentName } : undefined,
  });
  return data;
}

// PATCH /tickets/{ticket_id}
export async function updateTicket(
  ticketId: string,
  payload: TicketUpdateRequest,
  agentName?: string
): Promise<TicketResponse> {
  const { data } = await apiClient.patch<TicketResponse>(
    `/tickets/${ticketId}`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/transfer
export async function transferTicketAgent(
  ticketId: string,
  payload: TransferAgentRequest,
  agentName?: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/transfer`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}
