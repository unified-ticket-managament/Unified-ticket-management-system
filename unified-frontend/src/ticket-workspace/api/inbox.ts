import { apiClient } from "./client";
import type {
  AttachmentMeta,
  ComposeEmailResponse,
  DraftDeleteResponse,
  DraftListResponse,
  DraftSaveResponse,
  InboxResponse,
  InboxScope,
  InboxView,
  InteractionArchiveResponse,
  InteractionClaimResponse,
  InteractionFolderResponse,
  InteractionReplyRequest,
  InteractionReplyResponse,
  InteractionTagsResponse,
  OpenEmailResponse,
  SentResponse,
} from "@tw/types";

// GET /inbox — the current user's Account Manager inbox (their
// clients' mail; scope="all" is the Manager/Super Admin escape
// hatch to see every client's mail).
export async function getInbox(
  view: InboxView = "pending",
  options?: { clientId?: string; scope?: InboxScope; folderId?: string }
): Promise<InboxResponse> {
  const { data } = await apiClient.get<InboxResponse>("/inbox", {
    params: {
      view,
      client_id: options?.clientId,
      scope: options?.scope,
      folder_id: options?.folderId,
    },
  });
  return data;
}

// GET /inbox/sent — every reply the current user has sent, pre-
// ticket or ticket-level alike.
export async function getSent(): Promise<SentResponse> {
  const { data } = await apiClient.get<SentResponse>("/inbox/sent");
  return data;
}

// GET /inbox/drafts — every draft the current user currently has saved.
export async function getDrafts(): Promise<DraftListResponse> {
  const { data } = await apiClient.get<DraftListResponse>("/inbox/drafts");
  return data;
}

// PUT /inbox/{interaction_id}/draft — upsert the current user's
// draft reply (message + Cc/Bcc) on this thread.
export async function saveDraft(
  interactionId: string,
  message: string,
  cc: string[] = [],
  bcc: string[] = []
): Promise<DraftSaveResponse> {
  const { data } = await apiClient.put<DraftSaveResponse>(
    `/inbox/${interactionId}/draft`,
    { message, cc, bcc }
  );
  return data;
}

// POST /inbox/{interaction_id}/draft/attachments — attach files to
// the current user's in-progress draft on this thread. Works
// pre-ticket (unlike uploadAttachment in api/interaction.ts, which
// requires a real ticket_id) since attachments are always stored
// against an interaction_id at the data-model level.
export async function uploadDraftAttachment(
  interactionId: string,
  files: File[]
): Promise<AttachmentMeta[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<AttachmentMeta[]>(
    `/inbox/${interactionId}/draft/attachments`,
    formData
  );
  return data;
}

// POST /inbox/{interaction_id}/draft/send — send the current user's
// draft on this thread as a real reply. `toEmail`, when the agent
// picked a contact from the "To" dropdown, overrides the default
// recipient for this send only (not persisted onto the draft).
export async function sendDraft(
  interactionId: string,
  toEmail?: string | null
): Promise<InteractionReplyResponse> {
  const { data } = await apiClient.post<InteractionReplyResponse>(
    `/inbox/${interactionId}/draft/send`,
    { to_email: toEmail ?? null }
  );
  return data;
}

// DELETE /inbox/{interaction_id}/draft — discard the current user's
// draft on this thread without sending it.
export async function discardDraft(
  interactionId: string
): Promise<DraftDeleteResponse> {
  const { data } = await apiClient.delete<DraftDeleteResponse>(
    `/inbox/${interactionId}/draft`
  );
  return data;
}

// GET /inbox/{interaction_id}
export async function openInboxThread(
  interactionId: string
): Promise<OpenEmailResponse> {
  const { data } = await apiClient.get<OpenEmailResponse>(
    `/inbox/${interactionId}`
  );
  return data;
}

// POST /inbox/{interaction_id}/reply — reply on a bare (not-yet-
// ticketed) interaction, e.g. general communication that needs no
// ticket.
export async function replyToInteraction(
  interactionId: string,
  payload: InteractionReplyRequest
): Promise<InteractionReplyResponse> {
  const { data } = await apiClient.post<InteractionReplyResponse>(
    `/inbox/${interactionId}/reply`,
    payload
  );
  return data;
}

// POST /inbox/{interaction_id}/claim — "Assign to me". 409 if
// someone already claimed it first.
export async function claimInteraction(
  interactionId: string
): Promise<InteractionClaimResponse> {
  const { data } = await apiClient.post<InteractionClaimResponse>(
    `/inbox/${interactionId}/claim`
  );
  return data;
}

// POST /inbox/{interaction_id}/archive — "Informational / Archive":
// store it, no ticket, no work assignment.
export async function archiveInteraction(
  interactionId: string
): Promise<InteractionArchiveResponse> {
  const { data } = await apiClient.post<InteractionArchiveResponse>(
    `/inbox/${interactionId}/archive`
  );
  return data;
}

// PATCH /inbox/{interaction_id}/tags — full-replace the tag list.
export async function updateInteractionTags(
  interactionId: string,
  tags: string[]
): Promise<InteractionTagsResponse> {
  const { data } = await apiClient.patch<InteractionTagsResponse>(
    `/inbox/${interactionId}/tags`,
    { tags }
  );
  return data;
}

// PATCH /inbox/{interaction_id}/folder — file (or unfile, if
// folderId is null) into a custom folder.
export async function updateInteractionFolder(
  interactionId: string,
  folderId: string | null
): Promise<InteractionFolderResponse> {
  const { data } = await apiClient.patch<InteractionFolderResponse>(
    `/inbox/${interactionId}/folder`,
    { folder_id: folderId }
  );
  return data;
}

export interface ComposeEmailPayload {
  clientId: string;
  toEmail: string;
  subject: string;
  message: string;
  cc?: string[];
  bcc?: string[];
  files?: File[];
}

// POST /inbox/compose — author a brand-new outbound email to one of
// the platform's clients (the one Mail action with no existing
// interaction to reply onto). Multipart so attachments can ride
// along in the same request, same shape as uploadAttachment.
export async function composeEmail(
  payload: ComposeEmailPayload
): Promise<ComposeEmailResponse> {
  const formData = new FormData();
  formData.append("client_id", payload.clientId);
  formData.append("to_email", payload.toEmail);
  formData.append("subject", payload.subject);
  formData.append("message", payload.message);
  if (payload.cc?.length) formData.append("cc", payload.cc.join(","));
  if (payload.bcc?.length) formData.append("bcc", payload.bcc.join(","));
  payload.files?.forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<ComposeEmailResponse>(
    "/inbox/compose",
    formData
  );
  return data;
}
