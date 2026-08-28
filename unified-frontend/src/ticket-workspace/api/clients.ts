import { apiClient } from "./client";
import type {
  ClientContact,
  ClientCreateRequest,
  ClientDetailsResponse,
  ClientResponse,
} from "@tw/types";

// GET /clients — `mine: true` narrows the list to the calling Account
// Manager's own clients (a no-op for every other role); omitted for
// every caller that should keep seeing every client (Roles page
// roster, Rules engine picker, Create/Edit User contact prefill).
export async function listClients(options?: { mine?: boolean }): Promise<ClientResponse[]> {
  const { data } = await apiClient.get<ClientResponse[]>("/clients", {
    params: options?.mine ? { mine: true } : undefined,
  });
  return data;
}

// POST /clients
export async function createClient(
  payload: ClientCreateRequest
): Promise<ClientResponse> {
  const { data } = await apiClient.post<ClientResponse>("/clients", payload);
  return data;
}

// GET /clients/{client_id}/contacts — every personal address this
// client has previously contacted the shared inbox from, most-
// recently-used first. Backs the "To" dropdown on both reply
// composers (ticket + mail tab).
export async function listClientContacts(clientId: string): Promise<ClientContact[]> {
  const { data } = await apiClient.get<ClientContact[]>(`/clients/${clientId}/contacts`);
  return data;
}

// GET /clients/{client_id}/contacts?configured_only=true — just the
// curated client_contacts rows, no interaction-derived merge. Used by
// the Create/Edit User dialog's Client-role contact-email field — the
// merged listClientContacts() above would otherwise leak every
// person who's ever emailed in as an editable "contact", which the
// admin Save action would then permanently promote into the curated
// list on the next save. (The Roles page's own Client tab used to
// call this too; it now calls the client:view-gated
// getClientDetails() below instead — see that function's comment.)
export async function listConfiguredClientContacts(clientId: string): Promise<ClientContact[]> {
  const { data } = await apiClient.get<ClientContact[]>(
    `/clients/${clientId}/contacts`,
    { params: { configured_only: true } }
  );
  return data;
}

// GET /clients/{client_id}/details — aggregated detail view
// (organization email, account manager, configured contacts) gated by
// the client:view permission. Used ONLY by the Roles page's Client-
// tab expand action — every other client picker (Mail Compose, Mail
// filter, Rules engine, Create Dummy Mail) keeps calling the ungated
// listClients() above, and the Create/Edit User dialog keeps calling
// the ungated listConfiguredClientContacts() above, both untouched.
export async function getClientDetails(clientId: string): Promise<ClientDetailsResponse> {
  const { data } = await apiClient.get<ClientDetailsResponse>(`/clients/${clientId}/details`);
  return data;
}
