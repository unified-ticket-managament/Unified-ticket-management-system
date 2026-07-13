import { apiClient } from "./client";
import type {
  AttachmentUploadResponse,
  HideInteractionRequest,
  HideInteractionResponse,
  InteractionDirection,
  InteractionResponse,
  InteractionStatus,
  InternalNoteRequest,
  InternalNoteResponse,
  PriorityChangeRequest,
  ReplyRequest,
  StatusChangeRequest,
  ThreadResponse,
  TicketActionResponse,
  TicketInteractionResponse,
} from "@tw/types";

export interface ListTicketInteractionsParams {
  limit?: number;
  offset?: number;
  interactionType?: string;
  direction?: InteractionDirection;
  status?: InteractionStatus;
  agentId?: string;
  ticketId?: string;
  dateFrom?: string;
  dateTo?: string;
  search?: string;
}

export interface ListTicketInteractionsResult {
  items: TicketInteractionResponse[];
  total: number;
}

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
// the caller can see, instead of GET /tickets followed by one
// GET /tickets/{id}/interactions per ticket. Passing `limit` switches
// the backend to a bounded, filtered, server-paginated query and
// reports the matching total via the X-Total-Count response header
// (see unified-backend's list_all_ticket_interactions) — omitting it
// preserves the old unbounded-response shape, `total` just being
// `items.length`.
export async function getAllTicketInteractions(
  params: ListTicketInteractionsParams = {},
  signal?: AbortSignal
): Promise<ListTicketInteractionsResult> {
  const { data, headers } = await apiClient.get<TicketInteractionResponse[]>(
    "/tickets/interactions",
    {
      params: {
        limit: params.limit,
        offset: params.offset,
        interaction_type: params.interactionType,
        direction: params.direction,
        status: params.status,
        agent_id: params.agentId,
        ticket_id: params.ticketId,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        search: params.search,
      },
      signal,
    }
  );

  const totalHeader = headers["x-total-count"];
  return {
    items: data,
    total: totalHeader !== undefined ? Number(totalHeader) : data.length,
  };
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

// DELETE /attachments/{attachment_id} — remove an attachment (a
// ticket's or a draft's, both resolve through the same
// interaction-scoped authorization) before sending/regardless of
// ticket state.
export async function deleteAttachment(attachmentId: string): Promise<void> {
  await apiClient.delete(`/attachments/${attachmentId}`);
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
