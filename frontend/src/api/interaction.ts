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
  ResolveTicketRequest,
  StatusChangeRequest,
  TicketActionResponse,
} from "@/types";

// GET /tickets/{ticket_id}/interactions
export async function getTicketTimeline(
  ticketId: string,
  agentName?: string
): Promise<InteractionResponse[]> {
  const { data } = await apiClient.get<InteractionResponse[]>(
    `/tickets/${ticketId}/interactions`,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/notes
export async function addInternalNote(
  ticketId: string,
  payload: InternalNoteRequest,
  agentName?: string
): Promise<InternalNoteResponse> {
  const { data } = await apiClient.post<InternalNoteResponse>(
    `/tickets/${ticketId}/notes`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/reply
export async function replyToClient(
  ticketId: string,
  payload: ReplyRequest,
  agentName?: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/reply`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/status
export async function changeTicketStatus(
  ticketId: string,
  payload: StatusChangeRequest,
  agentName?: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/status`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/resolve
export async function resolveTicket(
  ticketId: string,
  payload: ResolveTicketRequest,
  agentName?: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/resolve`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/priority
export async function changeTicketPriority(
  ticketId: string,
  payload: PriorityChangeRequest,
  agentName?: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/priority`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /tickets/{ticket_id}/attachments
export async function uploadAttachment(
  ticketId: string,
  files: File[],
  agentName?: string
): Promise<AttachmentUploadResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (agentName) formData.append("agent_name", agentName);

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
  payload: HideInteractionRequest,
  agentName?: string
): Promise<HideInteractionResponse> {
  const { data } = await apiClient.post<HideInteractionResponse>(
    `/tickets/${ticketId}/interactions/${interactionId}/hide`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}

// POST /interactions/{interaction_id}/hide
// Ticket-agnostic soft delete — works for pending inbox emails too.
export async function hideInteractionById(
  interactionId: string,
  payload: HideInteractionRequest,
  agentName?: string
): Promise<HideInteractionResponse> {
  const { data } = await apiClient.post<HideInteractionResponse>(
    `/interactions/${interactionId}/hide`,
    payload,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}
