import { apiClient } from "./client";
import type { ClientContact, ClientCreateRequest, ClientResponse } from "@tw/types";

// GET /clients
export async function listClients(): Promise<ClientResponse[]> {
  const { data } = await apiClient.get<ClientResponse[]>("/clients");
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
