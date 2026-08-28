import { apiClient } from "./client";
import type {
  AttachmentUploadResponse,
  CancelSendResponse,
  DraftDeleteResponse,
  HideInteractionRequest,
  HideInteractionResponse,
  InlineImageUploadResponse,
  InteractionDirection,
  InteractionResponse,
  InteractionStatus,
  InternalNoteRecipientCandidate,
  InternalNoteRequest,
  InternalNoteResponse,
  PriorityChangeRequest,
  ReplyRequest,
  RetrySendResponse,
  StatusChangeRequest,
  ThreadResponse,
  TicketActionResponse,
  TicketAttachmentItem,
  TicketInteractionResponse,
  TicketNoteDraftResponse,
  TicketNoteDraftSaveRequest,
  TicketReplyDraftResponse,
  TicketReplyDraftSaveRequest,
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
  clientCompanyId?: string;
  ticketType?: string;
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

// GET /tickets/{ticket_id}/attachments — the ticket's complete
// attachment history across every interaction type. A dedicated
// endpoint, not derived from getTicketTimeline's own response: that
// endpoint is deliberately optimized to always return `attachments: []`
// per interaction (skipping signed-URL generation for the Timeline
// tab's own performance), so it was never a real source of attachment
// data despite TicketAttachmentsTab.tsx previously assuming it was.
export async function getTicketAttachments(
  ticketId: string
): Promise<TicketAttachmentItem[]> {
  const { data } = await apiClient.get<TicketAttachmentItem[]>(
    `/tickets/${ticketId}/attachments`
  );
  return data;
}

// GET /attachments/{id}/download — fetched (not navigated to) so the
// existing Authorization header applies and the bytes never require a
// live browser navigation to an external storage URL. UTMS is served
// over plain HTTP, and Chrome flags a direct navigation/anchor to the
// storage provider's own HTTPS URL as an "Insecure download" — saving
// from an in-memory blob instead avoids that external navigation
// entirely. Works for every attachment type; the caller supplies the
// filename already known from the attachment's own metadata.
export async function downloadAttachmentFile(
  attachmentId: string,
  filename: string
): Promise<void> {
  const { data } = await apiClient.get(`/attachments/${attachmentId}/download`, {
    responseType: "blob",
  });
  const blobUrl = window.URL.createObjectURL(data as Blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(blobUrl);
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
        client_company_id: params.clientCompanyId,
        ticket_type: params.ticketType,
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

// GET /tickets/internal-notes/recipients
export async function listInternalNoteRecipients(): Promise<InternalNoteRecipientCandidate[]> {
  const { data } = await apiClient.get<{ recipients: InternalNoteRecipientCandidate[] }>(
    "/tickets/internal-notes/recipients"
  );
  return data.recipients;
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

// Ticket-scoped drafts — Save Draft for Ticket Reply and Internal
// Note (also backs Mail's own ticketed ReplyComposer). See
// InteractionService's "Ticket Drafts" section for the full
// architecture rationale.

export async function saveTicketReplyDraft(
  ticketId: string,
  payload: TicketReplyDraftSaveRequest
): Promise<TicketReplyDraftResponse> {
  const { data } = await apiClient.put<TicketReplyDraftResponse>(
    `/tickets/${ticketId}/draft/reply`,
    payload
  );
  return data;
}

export async function getTicketReplyDraft(
  ticketId: string
): Promise<TicketReplyDraftResponse> {
  const { data } = await apiClient.get<TicketReplyDraftResponse>(
    `/tickets/${ticketId}/draft/reply`
  );
  return data;
}

export async function discardTicketReplyDraft(
  ticketId: string
): Promise<DraftDeleteResponse> {
  const { data } = await apiClient.delete<DraftDeleteResponse>(
    `/tickets/${ticketId}/draft/reply`
  );
  return data;
}

export async function sendTicketReplyDraft(
  ticketId: string,
  options?: { attachmentSourceInteractionId?: string; idempotencyKey?: string }
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/draft/reply/send`,
    null,
    {
      params: {
        attachment_source_interaction_id: options?.attachmentSourceInteractionId,
        idempotency_key: options?.idempotencyKey,
      },
    }
  );
  return data;
}

export async function saveTicketNoteDraft(
  ticketId: string,
  payload: TicketNoteDraftSaveRequest
): Promise<TicketNoteDraftResponse> {
  const { data } = await apiClient.put<TicketNoteDraftResponse>(
    `/tickets/${ticketId}/draft/note`,
    payload
  );
  return data;
}

export async function getTicketNoteDraft(ticketId: string): Promise<TicketNoteDraftResponse> {
  const { data } = await apiClient.get<TicketNoteDraftResponse>(
    `/tickets/${ticketId}/draft/note`
  );
  return data;
}

export async function discardTicketNoteDraft(ticketId: string): Promise<DraftDeleteResponse> {
  const { data } = await apiClient.delete<DraftDeleteResponse>(
    `/tickets/${ticketId}/draft/note`
  );
  return data;
}

export async function sendTicketNoteDraft(ticketId: string): Promise<InternalNoteResponse> {
  const { data } = await apiClient.post<InternalNoteResponse>(
    `/tickets/${ticketId}/draft/note/send`
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

// POST /tickets/{ticket_id}/attachments/inline-image — a single
// pasted-into-the-body screenshot (Outlook-style clipboard paste),
// distinct from the batch uploadAttachment above: one file, always
// inline, and the response carries a content_id the composer
// references as `cid:{content_id}` inside the HTML body it submits
// at send time (see lib/resolveInlineImageSources in lib/richText.ts).
export async function uploadTicketInlineImage(
  ticketId: string,
  file: File
): Promise<InlineImageUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await apiClient.post<InlineImageUploadResponse>(
    `/tickets/${ticketId}/attachments/inline-image`,
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

// POST /interactions/{interaction_id}/cancel-send — Undo Send (Issue
// 8). One route for every outbound path (Compose, ticket Reply,
// pre-ticket Reply/Draft-send) since they all now create the
// interaction the same PENDING_SEND way. The backend, not this
// request's own timing, is the sole authority on whether the window
// is still open — see InteractionService.cancel_pending_send.
export async function cancelSend(interactionId: string): Promise<CancelSendResponse> {
  const { data } = await apiClient.post<CancelSendResponse>(
    `/interactions/${interactionId}/cancel-send`
  );
  return data;
}

// POST /interactions/{interaction_id}/retry-send — Retry Send for a
// FAILED outbound Compose/Reply/Reply-All/Forward. Reuses the exact
// envelope persisted at send time; see InteractionService.
// retry_failed_send. A concurrent second retry (e.g. a double click)
// 400s rather than sending twice — surface the error, don't retry
// client-side.
export async function retrySend(interactionId: string): Promise<RetrySendResponse> {
  const { data } = await apiClient.post<RetrySendResponse>(
    `/interactions/${interactionId}/retry-send`
  );
  return data;
}
