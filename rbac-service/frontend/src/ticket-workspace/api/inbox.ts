import { apiClient } from "./client";
import type {
  InboxResponse,
  InboxScope,
  InboxView,
  InteractionArchiveResponse,
  InteractionClaimResponse,
  InteractionReplyRequest,
  InteractionReplyResponse,
  OpenEmailResponse,
} from "@tw/types";

// GET /inbox — the current user's Account Manager inbox (their
// clients' mail; scope="all" is the Manager/Super Admin escape
// hatch to see every client's mail).
export async function getInbox(
  view: InboxView = "pending",
  options?: { clientId?: string; scope?: InboxScope }
): Promise<InboxResponse> {
  const { data } = await apiClient.get<InboxResponse>("/inbox", {
    params: {
      view,
      client_id: options?.clientId,
      scope: options?.scope,
    },
  });
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
