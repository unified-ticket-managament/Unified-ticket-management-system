import { apiClient } from "./client";
import type { ClientCreateRequest, ClientResponse } from "@/types";

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
