import { apiClient } from "./client";
import type {
  AuditEntityType,
  AuditEventType,
  AuditLogResponse,
  TicketAuditLogResponse,
} from "@tw/types";

// Coalesces genuinely *concurrent* calls for the same ticket into one
// request, clearing the entry the instant it settles, so TicketAuditLog's
// own 10s poll always gets a fresh request rather than a stale cached one.
const inFlightByTicketId = new Map<string, Promise<AuditLogResponse[]>>();

// GET /tickets/{ticket_id}/audit-logs
export async function getTicketAuditLogs(ticketId: string): Promise<AuditLogResponse[]> {
  const existing = inFlightByTicketId.get(ticketId);
  if (existing) return existing;

  const promise = apiClient
    .get<AuditLogResponse[]>(`/tickets/${ticketId}/audit-logs`)
    .then(({ data }) => data)
    .finally(() => inFlightByTicketId.delete(ticketId));

  inFlightByTicketId.set(ticketId, promise);
  return promise;
}

export interface ListTicketAuditLogsParams {
  limit?: number;
  offset?: number;
  entityType?: AuditEntityType;
  eventType?: AuditEventType;
  actorName?: string;
  dateFrom?: string;
  dateTo?: string;
  search?: string;
}

export interface ListTicketAuditLogsResult {
  items: TicketAuditLogResponse[];
  total: number;
}

// GET /tickets/audit-logs — every audit-log row for every ticket the
// caller can see, in one request, instead of GET /tickets followed by
// one GET /tickets/{id}/audit-logs per ticket. Passing `limit` switches
// the backend to a bounded, filtered, server-paginated query and
// reports the matching total via the X-Total-Count response header —
// omitting it preserves the old unbounded-response shape.
export async function getAllTicketAuditLogs(
  params: ListTicketAuditLogsParams = {}
): Promise<ListTicketAuditLogsResult> {
  const { data, headers } = await apiClient.get<TicketAuditLogResponse[]>(
    "/tickets/audit-logs",
    {
      params: {
        limit: params.limit,
        offset: params.offset,
        entity_type: params.entityType,
        event_type: params.eventType,
        actor_name: params.actorName,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        search: params.search,
      },
    }
  );

  const totalHeader = headers["x-total-count"];
  return {
    items: data,
    total: totalHeader !== undefined ? Number(totalHeader) : data.length,
  };
}
