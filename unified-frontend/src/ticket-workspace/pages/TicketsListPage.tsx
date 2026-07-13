import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ArrowUpDown, MessagesSquare, Search, UserPlus } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import {
  claimTicket,
  getTicketViewCounts,
  listTicketsPage,
  type TicketViewCounts,
} from "@tw/api/ticket";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { useToast } from "@tw/context/ToastContext";
import { shortId, formatDateTime } from "@tw/lib/format";
import { isValidDateRange } from "@tw/lib/validation";
import { priorityTone, statusTone } from "@tw/lib/ticketTone";
import type { TicketPriority, TicketResponse, TicketStatus } from "@tw/types";

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
type PoolTab = "pool" | "mine" | "all";

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function TicketsListPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuthContext();
  const { categories } = useWorkflowContext();
  const { pushToast } = useToast();

  // Server-paginated/filtered/sorted rows for the current page —
  // this used to be "fetch every visible ticket, then filter/sort/
  // tab/paginate the whole thing in the browser," which downloads
  // and re-processes the entire ticket table on every visit and gets
  // strictly worse as the ticket count grows. Each tab/filter/sort/
  // page change now issues its own bounded request instead.
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [poolTab, setPoolTab] = useState<PoolTab>("pool");
  // The three tab badge counts, fetched independently via one grouped
  // query (GET /tickets/view-counts) instead of needing all three
  // tabs' full row sets just to show a number on each.
  const [viewCounts, setViewCounts] = useState<TicketViewCounts>({ pool: 0, mine: 0, all: 0 });

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

  const requestIdRef = useRef(0);
  const ticketsAbortRef = useRef<AbortController | null>(null);
  const countsAbortRef = useRef<AbortController | null>(null);

  const loadTickets = useCallback(
    async (pageToLoad: number) => {
      const requestId = ++requestIdRef.current;
      ticketsAbortRef.current?.abort();
      const controller = new AbortController();
      ticketsAbortRef.current = controller;
      setIsLoading(true);
      try {
        const offset = (pageToLoad - 1) * PAGE_SIZE;
        const result = await listTicketsPage(
          {
            limit: PAGE_SIZE,
            offset,
            view: poolTab,
            status: statusFilter === "ALL" ? undefined : statusFilter,
            priority: priorityFilter === "ALL" ? undefined : priorityFilter,
            ticketType: categoryFilter === "ALL" ? undefined : categoryFilter,
            search: debouncedSearch.trim() || undefined,
            dateFrom:
              dateFrom && isValidDateRange(dateFrom, dateTo)
                ? new Date(dateFrom).toISOString()
                : undefined,
            dateTo:
              dateTo && isValidDateRange(dateFrom, dateTo)
                ? new Date(`${dateTo}T23:59:59`).toISOString()
                : undefined,
            sortBy: sortKey,
            sortDir,
          },
          controller.signal
        );

        if (requestId !== requestIdRef.current) return;
        setTickets(result.items);
        setServerTotal(result.total);
        setLoadError(null);
      } catch (error) {
        if (requestId !== requestIdRef.current) return;
        if (error instanceof Error && error.name === "CanceledError") return;
        setLoadError(error instanceof Error ? error.message : "Failed to load tickets.");
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    },
    [poolTab, statusFilter, priorityFilter, categoryFilter, debouncedSearch, dateFrom, dateTo, sortKey, sortDir]
  );

  // Independent of loadTickets — the tab badges don't need to be
  // recomputed on every filter/sort/page change, only when the set of
  // visible tickets could plausibly have changed (mount, or a claim
  // action, see handleClaim below).
  const loadViewCounts = useCallback(async () => {
    countsAbortRef.current?.abort();
    const controller = new AbortController();
    countsAbortRef.current = controller;
    try {
      const counts = await getTicketViewCounts(controller.signal);
      setViewCounts(counts);
    } catch {
      // Non-essential — the tabs still work without a badge number.
    }
  }, []);

  const filterSignature = useMemo(
    () =>
      JSON.stringify([
        poolTab,
        debouncedSearch,
        statusFilter,
        priorityFilter,
        categoryFilter,
        dateFrom,
        dateTo,
        sortKey,
        sortDir,
      ]),
    [poolTab, debouncedSearch, statusFilter, priorityFilter, categoryFilter, dateFrom, dateTo, sortKey, sortDir]
  );
  const prevFilterSignatureRef = useRef(filterSignature);

  useEffect(() => {
    if (prevFilterSignatureRef.current !== filterSignature) {
      prevFilterSignatureRef.current = filterSignature;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    loadTickets(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSignature, page, loadTickets]);

  useEffect(() => {
    loadViewCounts();
  }, [loadViewCounts]);

  useEffect(() => {
    return () => {
      ticketsAbortRef.current?.abort();
      countsAbortRef.current?.abort();
    };
  }, []);

  const { run: runClaim, isLoading: isClaiming } = useApiAction(claimTicket, {
    successMessage: "Ticket claimed.",
  });
  const [claimingId, setClaimingId] = useState<string | null>(null);

  async function handleClaim(ticketId: string, e: React.MouseEvent) {
    e.stopPropagation();
    setClaimingId(ticketId);
    const result = await runClaim(ticketId);
    setClaimingId(null);
    // Claiming only ever sets agent_id on this one ticket (see
    // InteractionService.claim_ticket) — patch it in place instead of
    // refetching the whole page, but the tab badges (pool loses one,
    // mine gains one) do need a fresh grouped count.
    if (result && currentUser) {
      setTickets((prev) =>
        prev.map((t) =>
          t.ticket_id === ticketId
            ? { ...t, agent_id: currentUser.user_id, agent_name: currentUser.name }
            : t
        )
      );
      loadViewCounts();
    }
  }

  const totalPages = Math.max(1, Math.ceil(serverTotal / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);

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
      description={
        poolTab === "pool"
          ? "Unclaimed open tickets from every Account Manager — claim one to start working it."
          : poolTab === "mine"
          ? "Tickets currently claimed by you."
          : "Every ticket across every Account Manager."
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-1 rounded-md2 border border-border bg-surface p-1.5 shadow-xs">
          {(
            [
              { key: "pool" as const, label: "Open Pool", count: viewCounts.pool },
              { key: "mine" as const, label: "My Tickets", count: viewCounts.mine },
              { key: "all" as const, label: "All", count: viewCounts.all },
            ]
          ).map((tab) => {
            const isActive = poolTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => {
                  setPoolTab(tab.key);
                  setPage(1);
                }}
                aria-pressed={isActive}
                className={`flex items-center gap-1.5 rounded-md2 px-3 py-1.5 text-[12px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                  isActive
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:bg-surfaceHover hover:text-slate-700"
                }`}
              >
                {tab.label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                    isActive ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {tab.count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 rounded-md2 border border-border bg-surface p-3.5 shadow-xs">
          <div className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              placeholder="Search tickets by ID, subject, or client..."
              className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as TicketStatus | "ALL");
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

          {/* Team Lead/Staff are already scoped server-side to their
              own single category (see access_control.py's
              CATEGORY_SCOPED_ROLE_NAMES) — this filter would only ever
              offer one no-op option for them, so it's hidden entirely
              rather than shown as dead UI. Account Manager/Site Lead/
              Super Admin see every category and keep the real filter.
              Options come from WorkflowContext's session-cached
              categories list, not derived from the (no longer fully
              fetched) ticket rows themselves. */}
          {currentUser?.role !== "Team Lead" && currentUser?.role !== "Staff" && (
            <select
              value={categoryFilter}
              onChange={(e) => {
                setCategoryFilter(e.target.value);
              }}
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

          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                const value = e.target.value;
                setDateFrom(value);
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
            <Button size="sm" variant="secondary" onClick={() => loadTickets(page)}>
              Retry
            </Button>
          </div>
        )}

        <div className="overflow-hidden rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading && tickets.length === 0 ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : tickets.length === 0 ? (
            <EmptyState
              icon="🎫"
              title={serverTotal === 0 && !hasActiveFilters ? "No tickets yet" : "No tickets found"}
              description={
                serverTotal === 0 && !hasActiveFilters
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
                  {tickets.map((ticket) => (
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
                        {ticket.client_company_name ??
                          ticket.client_name ??
                          (ticket.client_id ? shortId(ticket.client_id) : "—")}
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
                          ticket.agent_id === currentUser?.user_id ? (
                            "You"
                          ) : (
                            ticket.agent_name ?? shortId(ticket.agent_id)
                          )
                        ) : (
                          <span className="text-muted">Unclaimed</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-xs text-muted">
                        {formatDateTime(ticket.updated_at)}
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-1">
                          {!ticket.agent_id && (
                            <Button
                              size="sm"
                              variant="primary"
                              isLoading={isClaiming && claimingId === ticket.ticket_id}
                              onClick={(e) => handleClaim(ticket.ticket_id, e)}
                            >
                              <UserPlus size={13} /> Claim
                            </Button>
                          )}
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

        {serverTotal > 0 && (
          <div className="flex items-center justify-between text-xs text-muted">
            <p>
              Showing{" "}
              <span className="font-medium text-slate-700">
                {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, serverTotal)}
              </span>{" "}
              of <span className="font-medium text-slate-700">{serverTotal}</span> tickets
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
