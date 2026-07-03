import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowUpDown, MessagesSquare, Search } from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { listTickets } from "@/api/ticket";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useWorkflowContext } from "@/context/WorkflowContext";
import { useToast } from "@/context/ToastContext";
import { shortId, formatDateTime } from "@/lib/format";
import { isValidDateRange } from "@/lib/validation";
import { priorityTone, statusTone } from "@/lib/ticketTone";
import type { TicketPriority, TicketResponse, TicketStatus } from "@/types";

const STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
  "CLOSED",
];
const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];
const PAGE_SIZE = 10;

type SortKey = "created_at" | "updated_at" | "title";

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function TicketsListPage() {
  const navigate = useNavigate();
  const { agentName } = useWorkflowContext();
  const { pushToast } = useToast();

  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "ALL">("ALL");
  const [priorityFilter, setPriorityFilter] = useState<TicketPriority | "ALL">("ALL");
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("updated_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await listTickets(agentName);
      setTickets(result);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Failed to load tickets.");
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  useEffect(() => {
    load();
  }, [load]);

  const categories = useMemo(
    () => Array.from(new Set(tickets.map((t) => t.ticket_type))).sort(),
    [tickets]
  );

  const filtered = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    return tickets.filter((t) => {
      if (
        term &&
        !t.title.toLowerCase().includes(term) &&
        !t.ticket_id.includes(term) &&
        !(t.client_name ?? "").toLowerCase().includes(term)
      ) {
        return false;
      }
      if (statusFilter !== "ALL" && t.current_status !== statusFilter) return false;
      if (priorityFilter !== "ALL" && t.current_priority !== priorityFilter) return false;
      if (categoryFilter !== "ALL" && t.ticket_type !== categoryFilter) return false;
      if (isValidDateRange(dateFrom, dateTo)) {
        if (dateFrom && new Date(t.created_at) < new Date(dateFrom)) return false;
        if (dateTo && new Date(t.created_at) > new Date(`${dateTo}T23:59:59`)) return false;
      }
      return true;
    });
  }, [tickets, debouncedSearch, statusFilter, priorityFilter, categoryFilter, dateFrom, dateTo]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "title") cmp = a.title.localeCompare(b.title);
      else cmp = new Date(a[sortKey]).getTime() - new Date(b[sortKey]).getTime();
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [filtered, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageItems = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(1);
  }

  function resetFilters() {
    setSearch("");
    setStatusFilter("ALL");
    setPriorityFilter("ALL");
    setCategoryFilter("ALL");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  }

  const hasActiveFilters =
    search || statusFilter !== "ALL" || priorityFilter !== "ALL" || categoryFilter !== "ALL" || dateFrom || dateTo;

  function SortHeader({ label, sortField }: { label: string; sortField: SortKey }) {
    const isActive = sortKey === sortField;
    return (
      <button
        className={`flex items-center gap-1.5 transition-colors ${isActive ? "text-slate-900" : "hover:text-slate-700"}`}
        onClick={() => toggleSort(sortField)}
      >
        {label}
        <ArrowUpDown size={11} className={isActive ? "text-accent" : "text-muted/60"} />
      </button>
    );
  }

  return (
    <AppLayout
      title="Tickets"
      description={`Tickets assigned to ${agentName}, plus anything still unassigned.`}
    >
      <div className="flex flex-col gap-4">
        <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 rounded-md2 border border-border bg-surface p-3.5 shadow-xs">
          <div className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search tickets by ID, subject, or client..."
              className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as TicketStatus | "ALL");
              setPage(1);
            }}
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
            onChange={(e) => {
              setPriorityFilter(e.target.value as TicketPriority | "ALL");
              setPage(1);
            }}
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

          <select
            value={categoryFilter}
            onChange={(e) => {
              setCategoryFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by category"
            className={selectClass}
          >
            <option value="ALL">All Categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                const value = e.target.value;
                setDateFrom(value);
                setPage(1);
                if (!isValidDateRange(value, dateTo)) {
                  pushToast("'From' date must be before or equal to the 'To' date.", "error");
                }
              }}
              aria-label="Created after date"
              className={selectClass}
            />
            <span className="text-xs text-muted">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                const value = e.target.value;
                setDateTo(value);
                setPage(1);
                if (!isValidDateRange(dateFrom, value)) {
                  pushToast("'From' date must be before or equal to the 'To' date.", "error");
                }
              }}
              aria-label="Created before date"
              className={selectClass}
            />
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={resetFilters}
            className={hasActiveFilters ? "" : "opacity-50"}
          >
            Reset
          </Button>
        </div>

        {loadError && (
          <div className="flex items-center justify-between gap-3 rounded-md2 border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
            <div className="flex items-center gap-2">
              <AlertTriangle size={15} className="flex-none" />
              <span>{loadError}</span>
            </div>
            <Button size="sm" variant="secondary" onClick={load}>
              Retry
            </Button>
          </div>
        )}

        <div className="overflow-hidden rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading && tickets.length === 0 ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : sorted.length === 0 ? (
            <EmptyState
              icon="🎫"
              title={tickets.length === 0 ? "No tickets yet" : "No tickets found"}
              description={
                tickets.length === 0
                  ? "Create a ticket from an inbox email to get started."
                  : "Try adjusting your filters, or create a ticket from an inbox email."
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="sticky top-0 z-10 border-b border-border bg-canvas text-left text-[10px] font-semibold uppercase tracking-wider text-muted">
                    <th className="px-5 py-3.5">Ticket ID</th>
                    <th className="px-5 py-3.5">
                      <SortHeader label="Subject" sortField="title" />
                    </th>
                    <th className="px-5 py-3.5">Client</th>
                    <th className="px-5 py-3.5">Status</th>
                    <th className="px-5 py-3.5">Priority</th>
                    <th className="px-5 py-3.5">Assigned Agent</th>
                    <th className="px-5 py-3.5">
                      <SortHeader label="Last Updated" sortField="updated_at" />
                    </th>
                    <th className="px-5 py-3.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {pageItems.map((ticket) => (
                    <tr
                      key={ticket.ticket_id}
                      onClick={() => navigate(`/tickets/${ticket.ticket_id}`)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          navigate(`/tickets/${ticket.ticket_id}`);
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={`Open ticket ${ticket.title}`}
                      className="cursor-pointer transition-colors hover:bg-surfaceHover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
                    >
                      <td className="px-5 py-3.5 font-mono text-xs text-muted">
                        {shortId(ticket.ticket_id)}
                      </td>
                      <td className="max-w-[240px] truncate px-5 py-3.5 font-medium text-slate-900">
                        {ticket.title}
                      </td>
                      <td className="px-5 py-3.5 text-slate-700">
                        {ticket.client_name ?? shortId(ticket.client_id)}
                      </td>
                      <td className="px-5 py-3.5">
                        <Badge tone={statusTone[ticket.current_status]} dot>
                          {ticket.current_status}
                        </Badge>
                      </td>
                      <td className="px-5 py-3.5">
                        <Badge tone={priorityTone[ticket.current_priority]}>
                          {ticket.current_priority}
                        </Badge>
                      </td>
                      <td className="px-5 py-3.5 text-slate-700">
                        {ticket.agent_id ? (
                          ticket.agent_name ?? shortId(ticket.agent_id)
                        ) : (
                          <span className="text-muted">Unassigned</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-xs text-muted">
                        {formatDateTime(ticket.updated_at)}
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={(e) => {
                              e.stopPropagation();
                              navigate(`/tickets/${ticket.ticket_id}`);
                            }}
                          >
                            View
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            title="View all interactions for this ticket"
                            aria-label={`View interactions for ${ticket.title}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              navigate(`/interactions?ticketId=${ticket.ticket_id}`);
                            }}
                          >
                            <MessagesSquare size={14} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {sorted.length > 0 && (
          <div className="flex items-center justify-between text-xs text-muted">
            <p>
              Showing{" "}
              <span className="font-medium text-slate-700">
                {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, sorted.length)}
              </span>{" "}
              of <span className="font-medium text-slate-700">{sorted.length}</span> tickets
            </p>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="px-1 font-medium text-slate-700">
                Page {currentPage} / {totalPages}
              </span>
              <Button
                size="sm"
                variant="secondary"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
