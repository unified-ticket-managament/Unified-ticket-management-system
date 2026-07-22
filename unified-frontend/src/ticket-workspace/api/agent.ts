import { apiClient } from "./client";
import type { AgentSummary, AssignableAgentsResponse } from "@tw/types";

// Cached per category key (the unscoped call uses "") for a short
// window. TicketActions and MessageDetailsView each independently
// request the active ticket's category-scoped agent list on every
// ticket mount/open — with no cache, reopening the same ticket, or two
// components mounted for the same ticket at once, reissued an identical
// GET /agents?category=... every time even though WorkflowContext
// already holds the unscoped list. A short TTL (not an unbounded cache)
// since a Staff member's active/inactive status can change between
// ticket opens.
const AGENTS_CACHE_TTL_MS = 30_000;
const cache = new Map<
  string,
  { promise: Promise<AgentSummary[]>; expiresAt: number }
>();

// GET /agents — omit `category` for every active Staff member;
// pass a ticket's `ticket_type` to scope results to that one
// work-specialization category (the Assign-to-Staff picker).
export async function listAgents(category?: string): Promise<AgentSummary[]> {
  const key = category ?? "";
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.promise;
  }

  const promise = apiClient
    .get<AgentSummary[]>("/agents", {
      params: category ? { category } : undefined,
    })
    .then(({ data }) => data);

  cache.set(key, { promise, expiresAt: now + AGENTS_CACHE_TTL_MS });
  // Don't let a failed fetch poison the cache for the next caller.
  promise.catch(() => cache.delete(key));

  return promise;
}

// GET /agents/assignable — who the current user may assign a
// brand-new ticket to on the Create Ticket dialog, scoped per their
// own role/hierarchy (see AssignmentService on the backend). Pass the
// dialog's currently-selected category so the Team Lead/Staff groups
// narrow to that one work-specialization team instead of listing
// every category's people at once — omit only if the category isn't
// known yet.
export async function listAssignableAgents(
  category?: string
): Promise<AssignableAgentsResponse> {
  const { data } = await apiClient.get<AssignableAgentsResponse>("/agents/assignable", {
    params: category ? { category } : undefined,
  });
  return data;
}
