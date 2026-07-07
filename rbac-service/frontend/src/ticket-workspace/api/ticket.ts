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
} from "@tw/types";

// GET /tickets
// Identity comes from the Bearer token — Staff sees only their own
// (plus unassigned) tickets, Team Lead/Manager/Super Admin see all.
export async function listTickets(): Promise<TicketResponse[]> {
  const { data } = await apiClient.get<TicketResponse[]>("/tickets");
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

// GET /tickets/{ticket_id}
export async function getTicket(ticketId: string): Promise<TicketResponse> {
  const { data } = await apiClient.get<TicketResponse>(`/tickets/${ticketId}`);
  return data;
}

// PATCH /tickets/{ticket_id}
export async function updateTicket(
  ticketId: string,
  payload: TicketUpdateRequest
): Promise<TicketResponse> {
  const { data } = await apiClient.patch<TicketResponse>(
    `/tickets/${ticketId}`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/transfer
export async function transferTicketAgent(
  ticketId: string,
  payload: TransferAgentRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/transfer`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/claim — pick up an unclaimed open
// ticket from the shared pool. 409 if someone already has it.
export async function claimTicket(
  ticketId: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/claim`
  );
  return data;
}
