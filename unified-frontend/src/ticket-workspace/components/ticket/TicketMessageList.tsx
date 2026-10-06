import { ArrowUpDown, Search, ShieldAlert, Lock, UserPlus } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { ClientFilterSelect } from "@tw/components/common/ClientFilterSelect";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import { shortId, formatDateTime, formatTicketNumber } from "@tw/lib/format";
import { priorityTone, statusTone } from "@tw/lib/ticketTone";
import type {
  CategoryResponse,
  ClientResponse,
  TicketPriority,
  TicketResponse,
  TicketStatus,
} from "@tw/types";

const STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
  "CLOSED",
];
const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

export type SortKey = "created_at" | "updated_at" | "title";

const selectClass =
  "rounded-md2 border border-border bg-surface px-2.5 py-1.5 text-[11px] font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

// Today/Yesterday/Last Week/Older — pure client-side grouping over
// each page's already-fetched `updated_at` field (no new data, no new
// API call). Order within each group is whatever the server already
// returned (respecting the current sort selection); this only adds
// section headers on top of it.
function groupByRecency(tickets: TicketResponse[]): Array<{ label: string; items: TicketResponse[] }> {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday);
  startOfYesterday.setDate(startOfYesterday.getDate() - 1);
  const startOfLastWeek = new Date(startOfToday);
  startOfLastWeek.setDate(startOfLastWeek.getDate() - 7);

  const buckets: Record<string, TicketResponse[]> = {
    Today: [],
    Yesterday: [],
    "Last Week": [],
    Older: [],
  };

  for (const ticket of tickets) {
    const updated = new Date(ticket.updated_at);
    if (updated >= startOfToday) buckets.Today.push(ticket);
    else if (updated >= startOfYesterday) buckets.Yesterday.push(ticket);
    else if (updated >= startOfLastWeek) buckets["Last Week"].push(ticket);
    else buckets.Older.push(ticket);
  }

  return ["Today", "Yesterday", "Last Week", "Older"]
    .map((label) => ({ label, items: buckets[label] }))
    .filter((group) => group.items.length > 0);
}

interface TicketMessageListProps {
  description: string;
  tickets: TicketResponse[];
  isLoading: boolean;
  loadError: string | null;
  onRetry: () => void;

  selectedTicketId: string | null;
  onOpenTicket: (ticketId: string) => void;

  selectedIds: Set<string>;
  onToggleSelect: (ticketId: string) => void;
  onToggleSelectAll: () => void;

  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: TicketStatus | "ALL";
  onStatusFilterChange: (value: TicketStatus | "ALL") => void;
  priorityFilter: TicketPriority | "ALL";
  onPriorityFilterChange: (value: TicketPriority | "ALL") => void;
  categoryFilter: string;
  onCategoryFilterChange: (value: string) => void;
  showCategoryFilter: boolean;
  categories: CategoryResponse[];
  clientFilter: string;
  onClientFilterChange: (value: string) => void;
  clients: ClientResponse[];
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onToggleSort: (key: SortKey) => void;
  hasActiveFilters: boolean;
  onResetFilters: () => void;

  page: number;
  totalPages: number;
  serverTotal: number;
  onPageChange: (page: number) => void;

  currentUserId: string | undefined;
  claimingId: string | null;
  isClaiming: boolean;
  onClaim: (ticketId: string, e: React.MouseEvent) => void;
  canAcknowledgeRow: (ticket: TicketResponse) => boolean;
  onOpenAcknowledge: (ticket: TicketResponse, e: React.MouseEvent) => void;
}

const ESCALATION_LEVEL_LABEL: Record<string, string> = {
  TEAM_LEAD: "Team Lead",
  MANAGER: "Manager",
  ASSIGNMENT_CHAIN: "Escalated",
  SITE_LEAD: "Site Lead",
};

export function TicketMessageList({
  description,
  tickets,
  isLoading,
  loadError,
  onRetry,
  selectedTicketId,
  onOpenTicket,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  priorityFilter,
  onPriorityFilterChange,
  categoryFilter,
  onCategoryFilterChange,
  showCategoryFilter,
  categories,
  clientFilter,
  onClientFilterChange,
  clients,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  sortKey,
  sortDir,
  onToggleSort,
  hasActiveFilters,
  onResetFilters,
  page,
  totalPages,
  serverTotal,
  onPageChange,
  currentUserId,
  claimingId,
  isClaiming,
  onClaim,
  canAcknowledgeRow,
  onOpenAcknowledge,
}: TicketMessageListProps) {
  const groups = groupByRecency(tickets);
  const allSelected = tickets.length > 0 && tickets.every((t) => selectedIds.has(t.ticket_id));

  function SortButton({ label, sortField }: { label: string; sortField: SortKey }) {
    const isActive = sortKey === sortField;
    return (
      <button
        type="button"
        onClick={() => onToggleSort(sortField)}
        className={`flex items-center gap-1 text-[11px] font-semibold transition-colors ${
          isActive ? "text-slate-900" : "text-muted hover:text-slate-700"
        }`}
      >
        {label}
        <ArrowUpDown size={10} className={isActive ? "text-accent" : "text-muted/60"} />
      </button>
    );
  }

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="flex flex-col gap-2 border-b border-border p-3">
        <p className="px-0.5 text-[12px] text-muted">{description}</p>
        <div className="relative">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search tickets by ID, subject, or client…"
            className="w-full rounded-md2 border border-border bg-canvas py-2 pl-8 pr-3 text-[12px] text-slate-900 shadow-xs placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <select
            value={statusFilter}
            onChange={(e) => onStatusFilterChange(e.target.value as TicketStatus | "ALL")}
            aria-label="Filter by status"
            className={selectClass}
          >
            <option value="ALL">All Statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            value={priorityFilter}
            onChange={(e) => onPriorityFilterChange(e.target.value as TicketPriority | "ALL")}
            aria-label="Filter by priority"
            className={selectClass}
          >
            <option value="ALL">All Priorities</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          {showCategoryFilter && (
            <select
              value={categoryFilter}
              onChange={(e) => onCategoryFilterChange(e.target.value)}
              aria-label="Filter by category"
              className={selectClass}
            >
              <option value="ALL">All Categories</option>
              {categories.map((c) => (
                <option key={c.category_id} value={c.category_name}>
                  {c.category_name}
                </option>
              ))}
            </select>
          )}
          <ClientFilterSelect
            clients={clients}
            categories={categories}
            value={clientFilter}
            onChange={onClientFilterChange}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={onResetFilters}
            className={hasActiveFilters ? "" : "opacity-50"}
          >
            Reset
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => onDateFromChange(e.target.value)}
            aria-label="Created after date"
            className={selectClass}
          />
          <span className="text-[11px] text-muted">to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => onDateToChange(e.target.value)}
            aria-label="Created before date"
            className={selectClass}
          />
        </div>
        <div className="flex items-center justify-between gap-2 px-0.5">
          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            <input type="checkbox" checked={allSelected} onChange={onToggleSelectAll} />
            Select all
          </label>
          <div className="flex items-center gap-2.5">
            <SortButton label="Updated" sortField="updated_at" />
            <SortButton label="Created" sortField="created_at" />
            <SortButton label="Subject" sortField="title" />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loadError && (
          <div className="m-3 flex items-center justify-between gap-3 rounded-md2 border border-danger/20 bg-danger/5 px-3 py-2.5 text-[12px] text-danger">
            <span>{loadError}</span>
            <Button size="sm" variant="secondary" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}

        {isLoading && tickets.length === 0 ? (
          <div className="p-4">
            <SkeletonRows rows={6} />
          </div>
        ) : tickets.length === 0 ? (
          <EmptyState
            icon="🎫"
            title={!hasActiveFilters ? "No tickets here" : "No tickets found"}
            description={
              !hasActiveFilters
                ? "Nothing in this view right now."
                : "Try adjusting your filters."
            }
          />
        ) : (
          groups.map((group) => (
            <div key={group.label} className="flex flex-col">
              <p className="sticky top-0 z-[1] bg-canvas px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
                {group.label}
              </p>
              {group.items.map((ticket) => {
                const isSelected = ticket.ticket_id === selectedTicketId;
                const isChecked = selectedIds.has(ticket.ticket_id);
                return (
                  <div
                    key={ticket.ticket_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => onOpenTicket(ticket.ticket_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onOpenTicket(ticket.ticket_id);
                      }
                    }}
                    className={`flex cursor-pointer items-start gap-2.5 border-b border-border px-4 py-3 transition-colors hover:bg-surfaceHover ${
                      isSelected ? "bg-accent/5" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => onToggleSelect(ticket.ticket_id)}
                      className="mt-1 flex-none"
                      aria-label={`Select ${ticket.title}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-[13px] font-semibold text-slate-900">
                          {ticket.title}
                        </p>
                        <p className="flex-none text-[10px] text-muted">
                          {formatDateTime(ticket.updated_at)}
                        </p>
                      </div>
                      <p className="mt-0.5 truncate text-[11px] text-muted">
                        {formatTicketNumber(ticket.ticket_number)} ·{" "}
                        {ticket.client_company_name ??
                          ticket.client_name ??
                          (ticket.client_id ? shortId(ticket.client_id) : "Unknown client")}
                      </p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <Badge tone={statusTone[ticket.current_status]} dot>
                          {ticket.current_status}
                        </Badge>
                        {ticket.is_escalated && ticket.escalation_status === "ACTIVE" ? (
                          <Badge tone="warning" icon={<Lock size={10} />}>
                            ESCALATED
                          </Badge>
                        ) : (
                          <Badge tone={priorityTone[ticket.current_priority]}>
                            {ticket.current_priority}
                          </Badge>
                        )}
                        {ticket.is_escalated && ticket.escalation_status === "ACKNOWLEDGED" && (
                          <ShieldAlert size={12} className="text-danger" aria-label="Escalated" />
                        )}
                        {ticket.resolution_sla_tier && ticket.resolution_sla_tier !== "healthy" && (
                          <SlaBadge tier={ticket.resolution_sla_tier} />
                        )}
                        <span className="text-[11px] text-muted">
                          {ticket.agent_id
                            ? ticket.agent_id === currentUserId
                              ? "You"
                              : ticket.agent_name ?? shortId(ticket.agent_id)
                            : "Unclaimed"}
                        </span>
                      </div>
                      {ticket.is_escalated && (
                        <p className="mt-1 text-[10px] text-muted">
                          {ticket.escalation_level
                            ? ESCALATION_LEVEL_LABEL[ticket.escalation_level] ?? ticket.escalation_level
                            : "Escalated"}
                          {" · "}
                          {ticket.escalation_status === "ACKNOWLEDGED"
                            ? "Acknowledged"
                            : ticket.escalation_ack_due_at
                              ? `Ack due ${formatDateTime(ticket.escalation_ack_due_at)}`
                              : "Awaiting acknowledgment"}
                        </p>
                      )}
                      <div className="mt-2 flex items-center gap-1.5">
                        {!ticket.agent_id && (
                          <Button
                            size="sm"
                            variant="primary"
                            isLoading={isClaiming && claimingId === ticket.ticket_id}
                            onClick={(e) => onClaim(ticket.ticket_id, e)}
                          >
                            <UserPlus size={12} /> Claim
                          </Button>
                        )}
                        {canAcknowledgeRow(ticket) && (
                          <Button size="sm" variant="primary" onClick={(e) => onOpenAcknowledge(ticket, e)}>
                            Acknowledge
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>

      {serverTotal > 0 && (
        <div className="flex flex-none items-center justify-between border-t border-border px-4 py-2 text-[11px] text-muted">
          <p>
            {(page - 1) * 10 + 1}–{Math.min(page * 10, serverTotal)} of {serverTotal}
          </p>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
              Prev
            </Button>
            <span className="px-1 font-medium text-slate-700">
              {page}/{totalPages}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
