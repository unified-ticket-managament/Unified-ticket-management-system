import { apiClient } from "./client";
import type {
  AttachInteractionRequest,
  AttachInteractionResponse,
  EditAccessApproveRequest,
  EditAccessRejectRequest,
  EditAccessRequestCreate,
  EditAccessRequestResponse,
  RelateTicketResponse,
  TicketActionResponse,
  TicketFromInteractionRequest,
  TicketFromInteractionResponse,
  TicketResponse,
  TicketUpdateRequest,
  TransferAgentRequest,
  UnrelateTicketResponse,
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

// POST /tickets/{ticket_id}/related — symmetric link, both tickets
// show each other under "Related Tickets" afterward.
export async function addRelatedTicket(
  ticketId: string,
  relatedTicketId: string
): Promise<RelateTicketResponse> {
  const { data } = await apiClient.post<RelateTicketResponse>(
    `/tickets/${ticketId}/related`,
    { related_ticket_id: relatedTicketId }
  );
  return data;
}

// DELETE /tickets/{ticket_id}/related/{related_ticket_id}
export async function removeRelatedTicket(
  ticketId: string,
  relatedTicketId: string
): Promise<UnrelateTicketResponse> {
  const { data } = await apiClient.delete<UnrelateTicketResponse>(
    `/tickets/${ticketId}/related/${relatedTicketId}`
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/request — ask to work a
// ticket you're not the assigned agent on and don't already hold
// ticket:editother_ticket for.
export async function requestEditAccess(
  ticketId: string,
  payload: EditAccessRequestCreate
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/request`,
    payload
  );
  return data;
}

// GET /tickets/{ticket_id}/edit-access
export async function listEditAccessRequests(
  ticketId: string
): Promise<EditAccessRequestResponse[]> {
  const { data } = await apiClient.get<EditAccessRequestResponse[]>(
    `/tickets/${ticketId}/edit-access`
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/{request_id}/approve
export async function approveEditAccess(
  ticketId: string,
  requestId: string,
  payload: EditAccessApproveRequest = {}
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/${requestId}/approve`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/{request_id}/reject
export async function rejectEditAccess(
  ticketId: string,
  requestId: string,
  payload: EditAccessRejectRequest = {}
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/${requestId}/reject`,
    payload
  );
  return data;
}
