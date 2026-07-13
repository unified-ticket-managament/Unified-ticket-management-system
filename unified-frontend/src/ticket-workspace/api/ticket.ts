import { apiClient } from "./client";
import type {
  AttachInteractionRequest,
  AttachInteractionResponse,
  EditAccessApproveRequest,
  EditAccessRejectRequest,
  EditAccessRequestCreate,
  EditAccessRequestResponse,
  RelateTicketResponse,
  TicketActionResponse,
  TicketFromInteractionRequest,
  TicketFromInteractionResponse,
  TicketResponse,
  TicketUpdateRequest,
  TransferAgentRequest,
  UnrelateTicketResponse,
} from "@tw/types";

// GET /tickets
// Identity comes from the Bearer token — Staff sees only their own
// (plus unassigned) tickets, Team Lead/Manager/Super Admin see all.
export async function listTickets(): Promise<TicketResponse[]> {
  const { data } = await apiClient.get<TicketResponse[]>("/tickets");
  return data;
}

export interface ListTicketsPageParams {
  limit: number;
  offset: number;
  status?: string;
  priority?: string;
  ticketType?: string;
  view?: "pool" | "mine" | "all";
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  sortBy?: "created_at" | "updated_at" | "title";
  sortDir?: "asc" | "desc";
}

export interface ListTicketsPageResult {
  items: TicketResponse[];
  total: number;
}

// GET /tickets, server-paginated/filtered/sorted — used by
// TicketsListPage instead of the unbounded listTickets() above, which
// fetches every visible ticket and does every filter/sort/tab/page
// slice in the browser. Reports the matching total via
// X-Total-Count so "Page X of Y" doesn't need a second request.
export async function listTicketsPage(
  params: ListTicketsPageParams,
  signal?: AbortSignal
): Promise<ListTicketsPageResult> {
  const { data, headers } = await apiClient.get<TicketResponse[]>("/tickets", {
    params: {
      limit: params.limit,
      offset: params.offset,
      status: params.status,
      priority: params.priority,
      ticket_type: params.ticketType,
      view: params.view,
      search: params.search,
      date_from: params.dateFrom,
      date_to: params.dateTo,
      sort_by: params.sortBy,
      sort_dir: params.sortDir,
    },
    signal,
  });

  const totalHeader = headers["x-total-count"];
  return {
    items: data,
    total: totalHeader !== undefined ? Number(totalHeader) : data.length,
  };
}

export interface TicketViewCounts {
  pool: number;
  mine: number;
  all: number;
}

// GET /tickets/view-counts — the three tab badges (Open Pool / My
// Tickets / All) in one grouped query, without fetching any tab's
// full row set just to show a count.
export async function getTicketViewCounts(
  signal?: AbortSignal
): Promise<TicketViewCounts> {
  const { data } = await apiClient.get<TicketViewCounts>("/tickets/view-counts", {
    signal,
  });
  return data;
}

// Only the fields the Dashboard's "Recent Activity"/"Needs Attention"
// lists actually render — the backend's DashboardStatsResponse omits
// custom_fields/related_tickets entirely (see that schema's own
// docstring), so this is deliberately narrower than the full
// TicketResponse rather than a type that doesn't match the real
// payload.
export type DashboardTicketSummary = Pick<
  TicketResponse,
  | "ticket_id"
  | "title"
  | "client_name"
  | "client_company_name"
  | "current_status"
  | "current_priority"
  | "updated_at"
>;

export interface DashboardStats {
  assigned: number;
  open: number;
  in_progress: number;
  resolved: number;
  resolved_today: number;
  closed: number;
  critical: number;
  sla_risk: number;
  recent_tickets: DashboardTicketSummary[];
  critical_tickets: DashboardTicketSummary[];
}

// GET /tickets/dashboard-stats — every stat card and small ticket
// list the Dashboard needs, computed server-side under real
// visibility scoping instead of the browser fetching every visible
// ticket (listTickets()) and deriving these numbers client-side.
export async function getDashboardStats(
  signal?: AbortSignal
): Promise<DashboardStats> {
  const { data } = await apiClient.get<DashboardStats>("/tickets/dashboard-stats", {
    signal,
  });
  return data;
}

// POST /tickets/from-interaction
export async function createTicketFromInteraction(
  payload: TicketFromInteractionRequest
): Promise<TicketFromInteractionResponse> {
  const { data } = await apiClient.post<TicketFromInteractionResponse>(
    "/tickets/from-interaction",
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/attach-interaction
export async function attachInteractionToTicket(
  ticketId: string,
  payload: AttachInteractionRequest
): Promise<AttachInteractionResponse> {
  const { data } = await apiClient.post<AttachInteractionResponse>(
    `/tickets/${ticketId}/attach-interaction`,
    payload
  );
  return data;
}

// GET /tickets/{ticket_id}
export async function getTicket(ticketId: string): Promise<TicketResponse> {
  const { data } = await apiClient.get<TicketResponse>(`/tickets/${ticketId}`);
  return data;
}

// PATCH /tickets/{ticket_id}
export async function updateTicket(
  ticketId: string,
  payload: TicketUpdateRequest
): Promise<TicketResponse> {
  const { data } = await apiClient.patch<TicketResponse>(
    `/tickets/${ticketId}`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/transfer
export async function transferTicketAgent(
  ticketId: string,
  payload: TransferAgentRequest
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/transfer`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/claim — pick up an unclaimed open
// ticket from the shared pool. 409 if someone already has it.
export async function claimTicket(
  ticketId: string
): Promise<TicketActionResponse> {
  const { data } = await apiClient.post<TicketActionResponse>(
    `/tickets/${ticketId}/claim`
  );
  return data;
}

// POST /tickets/{ticket_id}/related — symmetric link, both tickets
// show each other under "Related Tickets" afterward.
export async function addRelatedTicket(
  ticketId: string,
  relatedTicketId: string
): Promise<RelateTicketResponse> {
  const { data } = await apiClient.post<RelateTicketResponse>(
    `/tickets/${ticketId}/related`,
    { related_ticket_id: relatedTicketId }
  );
  return data;
}

// DELETE /tickets/{ticket_id}/related/{related_ticket_id}
export async function removeRelatedTicket(
  ticketId: string,
  relatedTicketId: string
): Promise<UnrelateTicketResponse> {
  const { data } = await apiClient.delete<UnrelateTicketResponse>(
    `/tickets/${ticketId}/related/${relatedTicketId}`
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/request — ask to work a
// ticket you're not the assigned agent on and don't already hold
// ticket:editother_ticket for.
export async function requestEditAccess(
  ticketId: string,
  payload: EditAccessRequestCreate
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/request`,
    payload
  );
  return data;
}

// GET /tickets/{ticket_id}/edit-access
export async function listEditAccessRequests(
  ticketId: string
): Promise<EditAccessRequestResponse[]> {
  const { data } = await apiClient.get<EditAccessRequestResponse[]>(
    `/tickets/${ticketId}/edit-access`
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/{request_id}/approve
export async function approveEditAccess(
  ticketId: string,
  requestId: string,
  payload: EditAccessApproveRequest = {}
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/${requestId}/approve`,
    payload
  );
  return data;
}

// POST /tickets/{ticket_id}/edit-access/{request_id}/reject
export async function rejectEditAccess(
  ticketId: string,
  requestId: string,
  payload: EditAccessRejectRequest = {}
): Promise<EditAccessRequestResponse> {
  const { data } = await apiClient.post<EditAccessRequestResponse>(
    `/tickets/${ticketId}/edit-access/${requestId}/reject`,
    payload
  );
  return data;
}
