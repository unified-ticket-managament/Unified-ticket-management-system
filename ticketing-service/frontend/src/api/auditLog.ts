import { apiClient } from "./client";
import type { AuditLogResponse } from "@/types";

// GET /tickets/{ticket_id}/audit-logs
export async function getTicketAuditLogs(ticketId: string): Promise<AuditLogResponse[]> {
  const { data } = await apiClient.get<AuditLogResponse[]>(
    `/tickets/${ticketId}/audit-logs`
  );
  return data;
}
