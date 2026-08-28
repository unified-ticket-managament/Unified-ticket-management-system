import { apiClient } from "./client";
import type {
  AttachmentMeta,
  ComposeDraftResponse,
  ComposeDraftSaveRequest,
  ComposeEmailResponse,
  DraftDeleteResponse,
  DraftListResponse,
  DraftSaveResponse,
  ForwardToInternalUserResponse,
  InboxResponse,
  InboxScope,
  InboxView,
  InlineImageUploadResponse,
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
  options?: {
    clientId?: string;
    scope?: InboxScope;
    folderId?: string;
    search?: string;
    limit?: number;
    offset?: number;
    category?: string;
    priority?: string;
    assignedToMe?: boolean;
  },
  signal?: AbortSignal
): Promise<InboxResponse> {
  const { data } = await apiClient.get<InboxResponse>("/inbox", {
    params: {
      view,
      client_id: options?.clientId,
      scope: options?.scope,
      folder_id: options?.folderId,
      search: options?.search,
      limit: options?.limit,
      offset: options?.offset,
      category: options?.category,
      priority: options?.priority,
      assigned_to_me: options?.assignedToMe,
    },
    signal,
  });
  return data;
}

// GET /inbox/folder-counts — every custom folder's item count in
// one query, under the same role scoping as GET /inbox. Replaces
// calling getInbox("all", {folderId}) once per folder just to read
// `.total`.
export async function getFolderCounts(
  clientId?: string
): Promise<Record<string, number>> {
  const { data } = await apiClient.get<Record<string, number>>("/inbox/folder-counts", {
    params: { client_id: clientId },
  });
  return data;
}

// GET /inbox/view-counts — Pending/Replied/Ticketed/Archived/All
// badge counts in one query, under the same role scoping as
// GET /inbox. Lets the sidebar show accurate tab counts without
// fetching each tab's actual row data until it's opened.
export async function getViewCounts(
  clientId?: string
): Promise<{ pending: number; replied: number; ticketed: number; archived: number; all: number }> {
  const { data } = await apiClient.get<{
    pending: number;
    replied: number;
    ticketed: number;
    archived: number;
    all: number;
  }>("/inbox/view-counts", { params: { client_id: clientId } });
  return data;
}

// GET /inbox/sent — every brand-new Compose email the current user has
// sent. See getReplied for replies — the two used to be merged here.
export async function getSent(): Promise<SentResponse> {
  const { data } = await apiClient.get<SentResponse>("/inbox/sent");
  return data;
}

// GET /inbox/replied — every reply the current user has sent, pre-
// ticket or ticket-level alike.
export async function getReplied(): Promise<SentResponse> {
  const { data } = await apiClient.get<SentResponse>("/inbox/replied");
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
  bcc: string[] = [],
  bodyHtml?: string | null
): Promise<DraftSaveResponse> {
  const { data } = await apiClient.put<DraftSaveResponse>(
    `/inbox/${interactionId}/draft`,
    { message, cc, bcc, body_html: bodyHtml ?? undefined }
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

// POST /inbox/{interaction_id}/draft/attachments/inline-image — the
// pre-ticket counterpart of uploadTicketInlineImage
// (api/interaction.ts), for a single pasted-into-the-body screenshot
// on a draft that hasn't become a ticket yet.
export async function uploadDraftInlineImage(
  interactionId: string,
  file: File
): Promise<InlineImageUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await apiClient.post<InlineImageUploadResponse>(
    `/inbox/${interactionId}/draft/attachments/inline-image`,
    formData
  );
  return data;
}

// POST /inbox/{interaction_id}/draft/send — send the current user's
// draft on this thread as a real reply. `toEmails`, when the agent
// picked one or more recipients from the "To" combobox, overrides the
// default recipient(s) for this send only (not persisted onto the
// draft).
export async function sendDraft(
  interactionId: string,
  toEmails?: string[],
  distributionListIds?: string[],
  // Client-generated Send idempotency key — see ComposeEmailPayload.
  // idempotencyKey above for the same additive contract. Previously
  // missing here entirely even though the backend's DraftSendRequest
  // already supports it.
  idempotencyKey?: string
): Promise<InteractionReplyResponse> {
  const { data } = await apiClient.post<InteractionReplyResponse>(
    `/inbox/${interactionId}/draft/send`,
    {
      to_emails: toEmails ?? [],
      distribution_list_ids: distributionListIds ?? [],
      idempotency_key: idempotencyKey,
    }
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

// GET /inbox/{interaction_id}. `markRead=false` fetches the thread's
// details without re-marking it read — for a refresh/re-open of an
// already-open thread, which shouldn't silently undo an explicit
// "Mark as Unread".
export async function openInboxThread(
  interactionId: string,
  markRead: boolean = true
): Promise<OpenEmailResponse> {
  const { data } = await apiClient.get<OpenEmailResponse>(
    `/inbox/${interactionId}`,
    { params: { mark_read: markRead } }
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

export interface ReadStatusResponse {
  interaction_id: string;
  is_read: boolean;
}

// POST /inbox/{interaction_id}/read — explicit "Mark as Read". The
// automatic mark-read-on-open path is openInboxThread itself (GET
// /inbox/{interaction_id} already records the receipt server-side);
// this is only for the manual toggle control.
export async function markInboxRead(
  interactionId: string
): Promise<ReadStatusResponse> {
  const { data } = await apiClient.post<ReadStatusResponse>(
    `/inbox/${interactionId}/read`
  );
  return data;
}

// POST /inbox/{interaction_id}/unread — explicit "Mark as Unread".
// Has no automatic counterpart — nothing else in Mail ever marks a
// thread unread.
export async function markInboxUnread(
  interactionId: string
): Promise<ReadStatusResponse> {
  const { data } = await apiClient.post<ReadStatusResponse>(
    `/inbox/${interactionId}/unread`
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
  // Exactly one of clientId/categoryId — the "From" mailbox this
  // message sends as. See ComposeEmailRequest's identical backend
  // docstring (schemas/compose.py).
  clientId?: string;
  categoryId?: string;
  // Optional — the primary/only recipient can instead come entirely
  // from distributionListIds (Compose has no fixed thread, so a
  // picked Distribution List becomes a genuine additional "To"
  // recipient). At least one of the two must resolve to a real
  // address or the backend 400s.
  toEmail?: string;
  // Every additional manually-typed "To" recipient past the first —
  // real recipients, sent to the backend's own to_emails (plural)
  // field, never downgraded into Cc (see ComposeEmailRequest's
  // backend docstring for the full rationale).
  toEmails?: string[];
  distributionListIds?: string[];
  subject: string;
  message: string;
  cc?: string[];
  bcc?: string[];
  files?: File[];
  // Optional sanitized-on-the-backend HTML counterpart to `message`
  // (Outlook-style clipboard paste — pasted rich text/tables/inline
  // images). Omit to send exactly like before this field existed.
  bodyHtml?: string | null;
  // Interaction ids returned by uploadComposeInlineImage for any
  // screenshot pasted into the editor before Send — reassigned onto
  // this message's own interaction server-side and embedded as a real
  // cid: inline image (see InteractionService.upload_compose_inline_
  // image / _merge_inline_images_into_envelope).
  inlineImageInteractionIds?: string[];
  // Client-generated Send idempotency key — a repeated request with
  // the same key (e.g. a client-side retry after a network hiccup)
  // returns the already-created interaction instead of sending a
  // second email. Generate a fresh one per Send attempt (e.g.
  // crypto.randomUUID()); omit to opt out entirely.
  idempotencyKey?: string;
}

// POST /inbox/compose/attachments/inline-image — stages a single
// pasted-into-the-body screenshot for a Compose or Forward message
// that hasn't been sent yet (neither has a pre-existing interaction
// to upload against the way a ticket reply/note does). Returns the
// same shape as uploadDraftInlineImage/uploadTicketInlineImage; the
// composer pushes result.interaction_id into inlineImageInteractionIds
// for the eventual composeEmail/forwardToInternalUser call.
export async function uploadComposeInlineImage(
  file: File
): Promise<InlineImageUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await apiClient.post<InlineImageUploadResponse>(
    "/inbox/compose/attachments/inline-image",
    formData
  );
  return data;
}

// POST /inbox/compose — author a brand-new outbound email to one of
// the platform's clients (the one Mail action with no existing
// interaction to reply onto). Multipart so attachments can ride
// along in the same request, same shape as uploadAttachment.
export async function composeEmail(
  payload: ComposeEmailPayload
): Promise<ComposeEmailResponse> {
  const formData = new FormData();
  if (payload.clientId) formData.append("client_id", payload.clientId);
  if (payload.categoryId) formData.append("category_id", payload.categoryId);
  if (payload.toEmail) formData.append("to_email", payload.toEmail);
  payload.toEmails?.forEach((email) => formData.append("to_emails", email));
  payload.distributionListIds?.forEach((id) => formData.append("distribution_list_ids", id));
  formData.append("subject", payload.subject);
  formData.append("message", payload.message);
  if (payload.cc?.length) formData.append("cc", payload.cc.join(","));
  if (payload.bcc?.length) formData.append("bcc", payload.bcc.join(","));
  if (payload.bodyHtml) formData.append("body_html", payload.bodyHtml);
  payload.files?.forEach((file) => formData.append("files", file));
  if (payload.inlineImageInteractionIds?.length) {
    formData.append(
      "inline_image_interaction_ids",
      payload.inlineImageInteractionIds.join(",")
    );
  }
  if (payload.idempotencyKey) formData.append("idempotency_key", payload.idempotencyKey);

  const { data } = await apiClient.post<ComposeEmailResponse>(
    "/inbox/compose",
    formData
  );
  return data;
}

// POST /inbox/compose-draft — creates a brand-new Compose draft (a
// parentless EMAIL-type root with is_draft=true). The one missing
// piece Compose needed to move off client-only localStorage — every
// subsequent save/attach/send/discard reuses this draft's own
// interaction_id, mirroring the pre-ticket Reply-draft flow above.
export async function createComposeDraft(
  payload: ComposeDraftSaveRequest
): Promise<ComposeDraftResponse> {
  const { data } = await apiClient.post<ComposeDraftResponse>(
    "/inbox/compose-draft",
    payload
  );
  return data;
}

// PUT /inbox/compose-draft/{interaction_id} — upserts the current
// user's Compose draft in place.
export async function saveComposeDraft(
  interactionId: string,
  payload: ComposeDraftSaveRequest
): Promise<ComposeDraftResponse> {
  const { data } = await apiClient.put<ComposeDraftResponse>(
    `/inbox/compose-draft/${interactionId}`,
    payload
  );
  return data;
}

// GET /inbox/compose-draft/{interaction_id} — fetches a Compose
// draft to restore its form on reopen/refresh.
export async function getComposeDraft(
  interactionId: string
): Promise<ComposeDraftResponse> {
  const { data } = await apiClient.get<ComposeDraftResponse>(
    `/inbox/compose-draft/${interactionId}`
  );
  return data;
}

// POST /inbox/compose-draft/{interaction_id}/attachments — attach
// files to the current user's in-progress Compose draft, uploaded
// immediately (before Send), same pattern as uploadDraftAttachment
// above for Reply drafts.
export async function uploadComposeDraftAttachment(
  interactionId: string,
  files: File[]
): Promise<AttachmentMeta[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const { data } = await apiClient.post<AttachmentMeta[]>(
    `/inbox/compose-draft/${interactionId}/attachments`,
    formData
  );
  return data;
}

// POST /inbox/compose-draft/{interaction_id}/send — sends the
// current user's Compose draft as a real outbound email.
export async function sendComposeDraft(
  interactionId: string,
  options?: {
    files?: File[];
    inlineImageInteractionIds?: string[];
    idempotencyKey?: string;
  }
): Promise<ComposeEmailResponse> {
  const formData = new FormData();
  options?.files?.forEach((file) => formData.append("files", file));
  if (options?.inlineImageInteractionIds?.length) {
    formData.append(
      "inline_image_interaction_ids",
      options.inlineImageInteractionIds.join(",")
    );
  }
  if (options?.idempotencyKey) formData.append("idempotency_key", options.idempotencyKey);

  const { data } = await apiClient.post<ComposeEmailResponse>(
    `/inbox/compose-draft/${interactionId}/send`,
    formData
  );
  return data;
}

// DELETE /inbox/compose-draft/{interaction_id} — discards the
// current user's Compose draft (and any of its attachments) without
// sending it.
export async function discardComposeDraft(
  interactionId: string
): Promise<DraftDeleteResponse> {
  const { data } = await apiClient.delete<DraftDeleteResponse>(
    `/inbox/compose-draft/${interactionId}`
  );
  return data;
}

export interface ForwardToInternalUserPayload {
  interactionId: string;
  // Exactly one of clientId/categoryId — see ComposeEmailPayload's
  // identical fields above.
  clientId?: string;
  categoryId?: string;
  // The union of all three is resolved/deduplicated server-side into
  // one final recipient list, sent as one send (see
  // InteractionService.forward_to_internal_user) — at least one of
  // the three must be non-empty.
  recipientUserIds?: string[];
  recipientEmails?: string[];
  distributionListIds?: string[];
  cc?: string[];
  bcc?: string[];
  subject: string;
  message: string;
  // Newly added attachments — combined server-side with whatever's
  // already stored against the original interaction, subject to the
  // 10-attachment total (see InteractionService.forward_to_internal_user).
  files?: File[];
  // Optional sanitized-on-the-backend HTML counterpart to `message`
  // (Outlook-style clipboard paste — see ComposeEmailPayload.bodyHtml
  // above for the same additive contract).
  bodyHtml?: string | null;
  // See ComposeEmailPayload.inlineImageInteractionIds — the same
  // staging mechanism (and the same uploadComposeInlineImage call) is
  // reused for Forward's own paste-a-screenshot case.
  inlineImageInteractionIds?: string[];
  // See ComposeEmailPayload.idempotencyKey — same contract.
  idempotencyKey?: string;
}

// POST /inbox/{interaction_id}/forward — forward an existing client
// email to either an internal organization user or an arbitrary
// external address. Multipart (like composeEmail above), not plain
// JSON: attachments already stored against the original interaction
// are always carried over server-side, and any newly uploaded `files`
// ride along in the same request.
export async function forwardToInternalUser(
  payload: ForwardToInternalUserPayload
): Promise<ForwardToInternalUserResponse> {
  const formData = new FormData();
  if (payload.clientId) formData.append("client_id", payload.clientId);
  if (payload.categoryId) formData.append("category_id", payload.categoryId);
  payload.recipientUserIds?.forEach((id) => formData.append("recipient_user_ids", id));
  payload.recipientEmails?.forEach((email) => formData.append("recipient_emails", email));
  payload.distributionListIds?.forEach((id) => formData.append("distribution_list_ids", id));
  if (payload.cc?.length) formData.append("cc", payload.cc.join(","));
  if (payload.bcc?.length) formData.append("bcc", payload.bcc.join(","));
  formData.append("subject", payload.subject);
  formData.append("message", payload.message);
  if (payload.bodyHtml) formData.append("body_html", payload.bodyHtml);
  payload.files?.forEach((file) => formData.append("files", file));
  if (payload.inlineImageInteractionIds?.length) {
    formData.append(
      "inline_image_interaction_ids",
      payload.inlineImageInteractionIds.join(",")
    );
  }
  if (payload.idempotencyKey) formData.append("idempotency_key", payload.idempotencyKey);

  const { data } = await apiClient.post<ForwardToInternalUserResponse>(
    `/inbox/${payload.interactionId}/forward`,
    formData
  );
  return data;
}
