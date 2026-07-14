import { apiClient } from "./client";
import type {
  SLAPolicyResponse,
  TicketActionResponse,
  TicketSLAResponse,
} from "@tw/types";

// GET /tickets/{ticket_id}/sla — accepts an AbortSignal so the 8s poll
// in useTicketSla can cancel a stale in-flight request at the network
// layer (ticket switch, unmount) instead of only discarding its result
// client-side after it completes.
export async function getTicketSla(
  ticketId: string,
  signal?: AbortSignal
): Promise<TicketSLAResponse> {
  const { data } = await apiClient.get<TicketSLAResponse>(`/tickets/${ticketId}/sla`, {
    signal,
  });
  return data;
}

// POST /tickets/{ticket_id}/sla/resume
export async function resumeTicketSla(ticketId: string): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/sla/resume`
  );
  return data;
}

// POST /tickets/{ticket_id}/escalate — ticket:escalate-gated on the
// backend; 400s if this ticket already has an active escalation.
export async function escalateTicket(ticketId: string): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/escalate`
  );
  return data;
}

// POST /tickets/{ticket_id}/escalation/acknowledge — only the current
// escalation level's own owner(s), or Site Lead/Super Admin, may call
// this (backend 403s otherwise).
export async function acknowledgeTicketEscalation(
  ticketId: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/escalation/acknowledge`
  );
  return data;
}

// GET /sla/policies — open to any authenticated user.
export async function listSlaPolicies(signal?: AbortSignal): Promise<SLAPolicyResponse[]> {
  const { data } = await apiClient.get<SLAPolicyResponse[]>("/sla/policies", { signal });
  return data;
}
