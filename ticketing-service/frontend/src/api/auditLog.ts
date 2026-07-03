import { apiClient } from "./client";
import type { AuditLogResponse } from "@/types";

// GET /tickets/{ticket_id}/audit-logs
export async function getTicketAuditLogs(
  ticketId: string,
  agentName?: string
): Promise<AuditLogResponse[]> {
  const { data } = await apiClient.get<AuditLogResponse[]>(
    `/tickets/${ticketId}/audit-logs`,
    { params: agentName ? { agent_name: agentName } : undefined }
  );
  return data;
}
