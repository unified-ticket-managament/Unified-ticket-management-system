// Pure, presentation-only aggregation helpers that bind the RBAC-native
// Dashboard/Reports pages to REAL backend ticket/audit-log data, replacing
// the mock-tickets.ts-derived calculations those two pages used before.
// Every function here takes already-fetched real API data (TicketResponse[]
// from the existing listTickets(), TicketAuditLogResponse[] from the
// existing getAllTicketAuditLogs()) and only does client-side counting/
// grouping/sorting — no new backend endpoint, no fabricated values.
import type {
  CategoryResponse,
  TicketAuditLogResponse,
  TicketPriority,
  TicketResponse,
} from "@tw/types";

const FINISHED_STATUSES = new Set(["RESOLVED", "CLOSED"]);

function isFinished(ticket: TicketResponse): boolean {
  return FINISHED_STATUSES.has(ticket.current_status);
}

// Semantic chart colors (blue/orange/green/purple/red/gray) — see the
// matching note in super-admin-dashboard.tsx/reports/page.tsx for why
// these live here instead of lib/mock-tickets.ts's PRIORITY_COLOR/
// STATUS_COLOR (whose `.bar` half is still read by viewer-dashboard.tsx).
const PRIORITY_LABEL: Record<TicketPriority, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  CRITICAL: "Critical",
};

// Fixed hex values (not Tailwind default-palette shades) so this exact
// scheme stays stable regardless of Tailwind's own default palette
// changing in a future upgrade — Low=Blue/Medium=Amber/High=Red/
// Critical=Purple, per the product's canonical priority color spec.
const PRIORITY_CHART_COLOR: Record<TicketPriority, string> = {
  LOW: "bg-[#3B82F6]",
  MEDIUM: "bg-[#F59E0B]",
  HIGH: "bg-[#EF4444]",
  CRITICAL: "bg-[#8B5CF6]",
};

const PRIORITY_ORDER: TicketPriority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

export const CATEGORY_CHART_COLOR_CYCLE = [
  "bg-blue-500",
  "bg-orange-500",
  "bg-green-500",
  "bg-purple-500",
  "bg-red-500",
  "bg-gray-400",
];

export function countsByPriorityFromTickets(tickets: TicketResponse[]) {
  return PRIORITY_ORDER.map((priority) => ({
    label: PRIORITY_LABEL[priority],
    value: tickets.filter((t) => t.current_priority === priority).length,
    color: PRIORITY_CHART_COLOR[priority],
  }));
}

export function countsByCategoryFromTickets(
  tickets: TicketResponse[],
  categories: CategoryResponse[]
) {
  return categories.map((category, i) => ({
    label: category.category_name,
    value: tickets.filter((t) => t.ticket_type === category.category_name).length,
    color: CATEGORY_CHART_COLOR_CYCLE[i % CATEGORY_CHART_COLOR_CYCLE.length],
  }));
}

// "Staff Performance" — resolved/closed count per agent, ranked
// descending. Agents with zero finished tickets don't appear (nothing
// to rank).
export function staffPerformanceFromTickets(tickets: TicketResponse[], topN = 6) {
  const counts = new Map<string, number>();
  for (const ticket of tickets) {
    if (!ticket.agent_name || !isFinished(ticket)) continue;
    counts.set(ticket.agent_name, (counts.get(ticket.agent_name) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, topN);
}

// "Team Performance" — the real backend has no distinct Team entity
// (confirmed: grouping only ever exists via category_id/Team Lead
// reporting, never a separate Team table), so this groups by each
// ticket's real category instead — the closest real, backend-native
// stand-in for a "team" that actually exists.
export function teamPerformanceFromTickets(tickets: TicketResponse[]) {
  const counts = new Map<string, number>();
  for (const ticket of tickets) {
    if (!isFinished(ticket)) continue;
    counts.set(ticket.ticket_type, (counts.get(ticket.ticket_type) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value);
}

// Buckets real tickets by created-month for the last `monthsBack` months
// (inclusive of the current month) — a real aggregation over real
// `created_at` timestamps, not a fabricated series.
export function monthlyTrendFromTickets(tickets: TicketResponse[], monthsBack = 6) {
  const now = new Date();
  const buckets = Array.from({ length: monthsBack }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - (monthsBack - 1 - i), 1);
    return { key: `${d.getFullYear()}-${d.getMonth()}`, label: d.toLocaleString("en-US", { month: "short" }), value: 0 };
  });
  const byKey = new Map(buckets.map((b) => [b.key, b]));

  for (const ticket of tickets) {
    const created = new Date(ticket.created_at);
    const bucket = byKey.get(`${created.getFullYear()}-${created.getMonth()}`);
    if (bucket) bucket.value += 1;
  }

  return buckets.map(({ label, value }) => ({ label, value }));
}

export interface ReportMetrics {
  total: number;
  resolved: number;
  pending: number;
  closed: number;
  avgResolutionHours: number;
  slaCompliance: number;
}

// Mirrors the exact same math the mock lib/mock-tickets.ts's
// getReportMetrics used (resolution time = finished-ticket end
// timestamp minus created_at; "pending" = everything not yet
// resolved/closed) — just fed by real tickets instead of MOCK_TICKETS.
// There is no persisted "resolved_at" on Ticket, only `closed_at`, so a
// RESOLVED-but-not-yet-closed ticket's `updated_at` is used as the best
// available real proxy for its resolution moment (same approximation
// the mock version already made).
export function reportMetricsFromTickets(tickets: TicketResponse[]): ReportMetrics {
  const total = tickets.length;
  const resolved = tickets.filter((t) => t.current_status === "RESOLVED").length;
  const closed = tickets.filter((t) => t.current_status === "CLOSED").length;
  const pending = total - resolved - closed;

  const finished = tickets.filter(isFinished);
  const avgResolutionHours =
    finished.length === 0
      ? 0
      : Math.round(
          (finished.reduce((sum, t) => {
            const end = new Date(t.closed_at ?? t.updated_at).getTime();
            const start = new Date(t.created_at).getTime();
            return sum + Math.max(0, end - start);
          }, 0) /
            finished.length /
            3_600_000) *
            10
        ) / 10;

  const measured = tickets.filter((t) => t.resolution_sla_tier != null);
  const compliant = measured.filter(
    (t) => t.resolution_sla_tier !== "breached" && t.resolution_sla_tier !== "escalated"
  );
  const slaCompliance = measured.length === 0 ? 100 : Math.round((compliant.length / measured.length) * 100);

  return { total, resolved, pending, closed, avgResolutionHours, slaCompliance };
}

// Average first-response time in minutes, derived without any N+1 loop:
// pairs each ticket's own real `created_at` against the earliest
// REPLY_ADDED audit-log event for that same ticket_id (one bulk audit-log
// query covers every ticket in scope, same endpoint Recent Activity
// already needs — see reports/page.tsx and super-admin-dashboard.tsx for
// the getAllTicketAuditLogs({ eventType: "REPLY_ADDED" }) call site).
export function avgResponseMinutesFromAuditLogs(
  tickets: TicketResponse[],
  replyAddedLogs: TicketAuditLogResponse[]
): number {
  const createdAtByTicketId = new Map(tickets.map((t) => [t.ticket_id, t.created_at]));
  const earliestReplyByTicketId = new Map<string, string>();

  for (const log of replyAddedLogs) {
    const existing = earliestReplyByTicketId.get(log.ticket_id);
    if (!existing || new Date(log.created_at) < new Date(existing)) {
      earliestReplyByTicketId.set(log.ticket_id, log.created_at);
    }
  }

  const minutesPerTicket: number[] = [];
  for (const [ticketId, replyAt] of earliestReplyByTicketId) {
    const createdAt = createdAtByTicketId.get(ticketId);
    if (!createdAt) continue;
    const minutes = (new Date(replyAt).getTime() - new Date(createdAt).getTime()) / 60_000;
    if (minutes >= 0) minutesPerTicket.push(minutes);
  }

  if (minutesPerTicket.length === 0) return 0;
  return Math.round(minutesPerTicket.reduce((a, b) => a + b, 0) / minutesPerTicket.length);
}
