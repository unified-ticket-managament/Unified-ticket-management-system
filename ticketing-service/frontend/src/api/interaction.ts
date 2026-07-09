import { apiClient } from "./client";
import type {
  AttachmentUploadResponse,
  HideInteractionRequest,
  HideInteractionResponse,
  InteractionResponse,
  InternalNoteRequest,
  InternalNoteResponse,
  PriorityChangeRequest,
  ReplyRequest,
  StatusChangeRequest,
  ThreadResponse,
  TicketActionResponse,
  TicketInteractionResponse,
} from "@/types";

// GET /tickets/{ticket_id}/interactions
export async function getTicketTimeline(
  ticketId: string
): Promise<InteractionResponse[]> {
  const { data } = await apiClient.get<InteractionResponse[]>(
    `/tickets/${ticketId}/interactions`
  );
  return data;
}

// GET /tickets/interactions — every interaction across every ticket
// the caller can see, in one request, instead of GET /tickets
// followed by one GET /tickets/{id}/interactions per ticket.
export async function getAllTicketInteractions(): Promise<TicketInteractionResponse[]> {
  const { data } = await apiClient.get<TicketInteractionResponse[]>("/tickets/interactions");
  return data;
}

// GET /interactions/{interaction_id}/thread — the full conversation
// (parent + every reply) for any id within it, so a single flattened
// timeline row can be opened in its full thread context.
export async function getInteractionThread(interactionId: string): Promise<ThreadResponse> {
  const { data } = await apiClient.get<ThreadResponse>(
    `/interactions/${interactionId}/thread`
  );
  return data;
}

// POST /tickets/{ticket_id}/notes
export async function addInternalNote(
  ticketId: string,
  payload: InternalNoteRequest
): Promise<InternalNoteResponse> {
  const { data } = await apiClient.post<InternalNoteResponse>(
    `/tickets/${ticketId}/notes`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/reply
export async function replyToClient(
  ticketId: string,
  payload: ReplyRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/reply`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/status
export async function changeTicketStatus(
  ticketId: string,
  payload: StatusChangeRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/status`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/priority
export async function changeTicketPriority(
  ticketId: string,
  payload: PriorityChangeRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/priority`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/attachments
export async function uploadAttachment(
  ticketId: string,
  files: File[]
): Promise<AttachmentUploadResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<AttachmentUploadResponse>(
    `/tickets/${ticketId}/attachments`,
    formData
  );
  return data;
}

// POST /tickets/{ticket_id}/interactions/{interaction_id}/hide
export async function hideInteraction(
  ticketId: string,
  interactionId: string,
  payload: HideInteractionRequest
): Promise<HideInteractionResponse> {
  const { data } = await apiClient.post<HideInteractionResponse>(
    `/tickets/${ticketId}/interactions/${interactionId}/hide`,
    payload
  );
  return data;
}

// POST /interactions/{interaction_id}/hide
// Ticket-agnostic soft delete — works for pending inbox emails too.
export async function hideInteractionById(
  interactionId: string,
  payload: HideInteractionRequest
): Promise<HideInteractionResponse> {
  const { data } = await apiClient.post<HideInteractionResponse>(
    `/interactions/${interactionId}/hide`,
    payload
  );
  return data;
}
