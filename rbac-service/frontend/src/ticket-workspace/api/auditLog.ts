import { apiClient } from "./client";
import type { AuditLogResponse, TicketAuditLogResponse } from "@tw/types";

// GET /tickets/{ticket_id}/audit-logs
export async function getTicketAuditLogs(ticketId: string): Promise<AuditLogResponse[]> {
  const { data } = await apiClient.get<AuditLogResponse[]>(
    `/tickets/${ticketId}/audit-logs`
  );
  return data;
}

// GET /tickets/audit-logs — every audit-log row for every ticket the
// caller can see, in one request, instead of GET /tickets followed by
// one GET /tickets/{id}/audit-logs per ticket.
export async function getAllTicketAuditLogs(): Promise<TicketAuditLogResponse[]> {
  const { data } = await apiClient.get<TicketAuditLogResponse[]>("/tickets/audit-logs");
  return data;
}
