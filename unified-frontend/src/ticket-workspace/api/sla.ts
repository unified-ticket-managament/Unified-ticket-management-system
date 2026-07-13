import { apiClient } from "./client";
import type {
  SLAPauseRequest,
  SLAPolicyResponse,
  TicketActionResponse,
  TicketSLAResponse,
} from "@tw/types";

// GET /tickets/{ticket_id}/sla
export async function getTicketSla(ticketId: string): Promise<TicketSLAResponse> {
  const { data } = await apiClient.get<TicketSLAResponse>(`/tickets/${ticketId}/sla`);
  return data;
}

// POST /tickets/{ticket_id}/sla/pause — supervisor-only on the backend;
// non-supervisors get a 403 handled the same way any other action
// error is (useApiAction's toast).
export async function pauseTicketSla(
  ticketId: string,
  payload: SLAPauseRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/sla/pause`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/sla/resume
export async function resumeTicketSla(ticketId: string): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/sla/resume`
  );
  return data;
}

// GET /sla/policies — open to any authenticated user.
export async function listSlaPolicies(): Promise<SLAPolicyResponse[]> {
  const { data } = await apiClient.get<SLAPolicyResponse[]>("/sla/policies");
  return data;
}
