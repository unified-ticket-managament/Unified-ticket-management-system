import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Globe, Lock, RefreshCw, Search, SlidersHorizontal } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { AuditLogDetailsDrawer } from "@tw/components/common/AuditLogDetailsDrawer";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { getAllTicketAuditLogs } from "@tw/api/auditLog";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import { formatDateTime } from "@tw/lib/format";
import { auditMetaFor, diffFields, formatFieldValue, humanizeFieldKey } from "@tw/lib/auditLogMeta";
import { isSupervisorRole } from "@/lib/role-access";
import type { ActorRole, AuditEntityType, AuditEventType } from "@tw/types";

interface AuditRow {
  auditId: string;
  createdAt: string;
  entityType: AuditEntityType;
  eventType: AuditEventType;
  actorName: string;
  actorRole: ActorRole;
  ticketId: string;
  ticketTitle: string;
  oldValues: Record<string, unknown> | null;
  newValues: Record<string, unknown> | null;
}

const ACTOR_ROLE_LABEL: Record<ActorRole, string> = {
  AGENT: "Agent",
  CLIENT: "Client",
  SYSTEM: "System",
};

const ENTITY_TYPES: AuditEntityType[] = ["TICKET", "INTERACTION", "ATTACHMENT", "CLIENT", "USER"];
const EVENT_TYPES: AuditEventType[] = [
  "TICKET_CREATED",
  "TICKET_UPDATED",
  "TICKET_RESOLVED",
  "STATUS_CHANGED",
  "PRIORITY_CHANGED",
  "AGENT_TRANSFERRED",
  "TICKET_CLAIMED",
  "INTERACTION_HIDDEN",
  "ATTACHMENT_UPLOADED",
  "NOTE_ADDED",
  "REPLY_ADDED",
  "EMAIL_RECEIVED",
  "CLIENT_CREATED",
  "INTERACTION_CLAIMED",
  "INTERACTION_ARCHIVED",
  "EDIT_ACCESS_REQUESTED",
  "EDIT_ACCESS_APPROVED",
  "EDIT_ACCESS_REJECTED",
];

const POLL_INTERVAL_MS = 15_000;
const PAGE_SIZE = 15;

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function AuditLogPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuthContext();
  const { agents } = useWorkflowContext();

  // Super Admin/Site Lead always see the unrestricted, company-wide
  // log — same as before this change, no button, no toggle. Everyone
  // else (Account Manager/Team Lead/Staff) defaults to a scoped view
  // (own clients / own team / own tickets — see the backend's
  // list_all_audit_logs) and can only reach the centralized view by
  // explicitly switching into it, and only once granted
  // ticket:view_global_audit_log.
  const isGlobalRole = isSupervisorRole(currentUser?.role);
  const canViewGlobalAuditLog = (currentUser?.permissions ?? []).includes(
    "ticket:view_global_audit_log"
  );
  const [centralizedMode, setCentralizedMode] = useState(false);
  const effectiveCentralized = isGlobalRole || centralizedMode;

  // The current server page only (server-paginated/filtered now) —
  // this used to be every visible audit-log row ever written, fetched
  // and re-filtered/re-paginated client-side on every 15s poll tick,
  // which meant every connected agent's browser re-fetched the entire
  // audit history forever as it grew.
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const requestIdRef = useRef(0);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [entityFilter, setEntityFilter] = useState<AuditEntityType | "ALL">("ALL");
  const [eventFilter, setEventFilter] = useState<AuditEventType | "ALL">("ALL");
  const [agentFilter, setAgentFilter] = useState("ALL");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<AuditRow | null>(null);

  const load = useCallback(
    async (pageToLoad: number, showLoading: boolean) => {
      const requestId = ++requestIdRef.current;
      if (showLoading) setIsLoading(true);
      try {
        const offset = (pageToLoad - 1) * PAGE_SIZE;
        // Same visibility scoping as every other cross-ticket view in
        // this app (Interactions page, Inbox): this agent's tickets
        // plus anything still unassigned. One request for the current
        // page of every visible ticket's audit trail, instead of
        // GET /tickets followed by one GET .../audit-logs per ticket
        // — and, since this session's pagination work, instead of the
        // entire unbounded history on every load and every poll tick.
        const result = await getAllTicketAuditLogs({
          limit: PAGE_SIZE,
          offset,
          entityType: entityFilter === "ALL" ? undefined : entityFilter,
          eventType: eventFilter === "ALL" ? undefined : eventFilter,
          actorName: agentFilter === "ALL" ? undefined : agentFilter,
          dateFrom: dateFrom ? new Date(dateFrom).toISOString() : undefined,
          dateTo: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
          search: debouncedSearch.trim() || undefined,
          centralized: effectiveCentralized,
        });

        // A newer load already started (a filter/page change, manual
        // refresh, or the next poll tick) — this response is stale,
        // drop it rather than overwriting fresher data with older data.
        if (requestId !== requestIdRef.current) return;

        const merged = result.items.map<AuditRow>((log) => ({
          auditId: log.audit_id,
          createdAt: log.created_at,
          entityType: log.entity_type,
          eventType: log.event_type,
          actorName: log.actor_name,
          actorRole: log.actor_role,
          ticketId: log.ticket_id,
          ticketTitle: log.ticket_title,
          oldValues: log.old_values,
          newValues: log.new_values,
        }));
        // Already newest-first from the backend — no client re-sort.
        setRows(merged);
        setServerTotal(result.total);
        setLoadError(null);
      } catch (error) {
        if (requestId !== requestIdRef.current) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load audit logs.");
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    },
    [entityFilter, eventFilter, agentFilter, dateFrom, dateTo, debouncedSearch, effectiveCentralized]
  );

  // The poll interval below is only ever created once (on mount), but
  // each tick must use whatever page/filters are current *at that
  // moment*, not whatever they were when the interval was created —
  // these refs are updated every render so the interval's closure
  // always reads the latest values without needing to be torn down
  // and recreated on every filter/page change.
  const loadRef = useRef(load);
  loadRef.current = load;
  const pageRef = useRef(page);
  pageRef.current = page;

  // Drives every fetch: a page change (Next/Previous) or a filter
  // change, but never both as two separate round trips for one user
  // action — same pattern as InteractionsPage.tsx. A filter change
  // resets to page 1; if we're not already there, this effect only
  // calls setPage(1) and returns (no fetch), and the resulting
  // re-render (page now 1) re-runs this same effect to do the actual
  // fetch. Fetching unconditionally here would double-fetch: once for
  // the old page with the new filters, once more for page 1.
  const filterSignature = useMemo(
    () =>
      JSON.stringify([
        debouncedSearch,
        entityFilter,
        eventFilter,
        agentFilter,
        dateFrom,
        dateTo,
        effectiveCentralized,
      ]),
    [debouncedSearch, entityFilter, eventFilter, agentFilter, dateFrom, dateTo, effectiveCentralized]
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
    load(page, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSignature, page, load]);

  useEffect(() => {
    const interval = window.setInterval(
      () => loadRef.current(pageRef.current, false),
      POLL_INTERVAL_MS
    );
    return () => window.clearInterval(interval);
  }, []);

  const totalPages = Math.max(1, Math.ceil(serverTotal / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);

  const hasActiveFilters = Boolean(
    debouncedSearch.trim() ||
      entityFilter !== "ALL" ||
      eventFilter !== "ALL" ||
      agentFilter !== "ALL" ||
      dateFrom ||
      dateTo
  );

  function handleRowClick(row: AuditRow) {
    setDrawerRow(row);
    setDrawerOpen(true);
  }

  function closeDrawer() {
    setDrawerOpen(false);
  }

  function handleViewTicket(ticketId: string) {
    setDrawerOpen(false);
    navigate(`/tickets/${ticketId}`);
  }

  const scopeDescription = isGlobalRole
    ? "Immutable record of every ticket change across the system."
    : effectiveCentralized
      ? "Immutable record of every ticket change across the entire system (centralized view)."
      : currentUser?.role === "Account Manager"
        ? "Immutable record of every ticket change across your assigned clients."
        : currentUser?.role === "Team Lead"
          ? "Immutable record of every ticket change across your team."
          : `Immutable record of every ticket change for tickets assigned to ${currentUser?.name}.`;

  return (
    <AppLayout
      title="Audit Logs"
      description={scopeDescription}
      action={
        !isGlobalRole ? (
          <Button
            size="sm"
            variant={centralizedMode ? "primary" : "secondary"}
            className="gap-1.5"
            disabled={!canViewGlobalAuditLog}
            title={
              canViewGlobalAuditLog
                ? undefined
                : "You don't have permission to view the centralized audit log."
            }
            onClick={() => setCentralizedMode((v) => !v)}
          >
            <Globe size={14} />
            {centralizedMode ? "Back to My Scoped Audit Log" : "View Centralized Audit Log"}
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4">
        {!isGlobalRole && centralizedMode && (
          <div>
            <Badge tone="info">Centralized Audit View</Badge>
          </div>
        )}

        <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 rounded-md2 border border-border bg-surface p-3.5 shadow-xs">
          <div className="relative min-w-[220px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by ticket title..."
              className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
          </div>

          <div className="hidden items-center gap-1.5 text-muted sm:flex">
            <SlidersHorizontal size={13} />
          </div>

          <select
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value as AuditEntityType | "ALL")}
            aria-label="Filter by entity type"
            className={selectClass}
          >
            <option value="ALL">All Entities</option>
            {ENTITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <select
            value={eventFilter}
            onChange={(e) => setEventFilter(e.target.value as AuditEventType | "ALL")}
            aria-label="Filter by event type"
            className={selectClass}
          >
            <option value="ALL">All Events</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {auditMetaFor(t).label}
              </option>
            ))}
          </select>

          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            aria-label="Filter by agent"
            className={selectClass}
          >
            <option value="ALL">All Agents</option>
            {agents.map((a) => (
              <option key={a.user_id} value={a.name}>
                {a.name}
              </option>
            ))}
          </select>

          <div className="flex items-center gap-1.5">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              aria-label="From date"
              className={selectClass}
            />
            <span className="text-xs text-muted">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              aria-label="To date"
              className={selectClass}
            />
          </div>

          <Button
            size="sm"
            variant="ghost"
            isLoading={isLoading}
            onClick={() => load(page, true)}
            aria-label="Refresh audit log"
          >
            <RefreshCw size={14} />
          </Button>

          <span
            title="Audit entries are immutable — they are never edited or deleted."
            className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted"
          >
            <Lock size={11} /> Read-only
          </span>
        </div>

        {loadError && (
          <div className="flex items-center justify-between gap-3 rounded-md2 border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
            <div className="flex items-center gap-2">
              <AlertTriangle size={15} className="flex-none" />
              <span>{loadError}</span>
            </div>
            <Button size="sm" variant="secondary" onClick={() => load(page, true)}>
              Retry
            </Button>
          </div>
        )}

        <div className="rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading && rows.length === 0 ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : rows.length === 0 ? (
            <EmptyState
              icon="🔒"
              title={!hasActiveFilters && page === 1 ? "No audit events yet" : "No audit events found"}
              description={
                !hasActiveFilters && page === 1
                  ? "Ticket changes will appear here permanently once they happen."
                  : "Try adjusting your filters."
              }
            />
          ) : (
            <>
              <ul className="divide-y divide-border">
                {rows.map((row) => {
                  const meta = auditMetaFor(row.eventType);
                  const fields = diffFields(row.oldValues, row.newValues);

                  return (
                    <li
                      key={row.auditId}
                      className="flex items-center transition-colors hover:bg-surfaceHover"
                    >
                      <button
                        onClick={() => handleRowClick(row)}
                        aria-label={`${meta.label} on ${row.ticketTitle}`}
                        className="flex flex-1 items-center gap-3.5 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
                      >
                        <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                          {meta.icon}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={meta.tone}>{meta.label}</Badge>
                            <span className="truncate text-xs text-muted">
                              on <span className="font-medium text-slate-500">{row.ticketTitle}</span>
                            </span>
                          </div>
                          {fields.length > 0 && (
                            <p className="mt-1 truncate text-[13px] text-slate-600">
                              {fields
                                .map(
                                  (f) =>
                                    `${humanizeFieldKey(f.key)}: ${formatFieldValue(f.to)}`
                                )
                                .join(" · ")}
                            </p>
                          )}
                        </div>
                        <div className="flex-none text-right">
                          <p className="text-xs font-medium text-slate-600">{formatDateTime(row.createdAt)}</p>
                          <p className="mt-0.5 text-[11px] text-muted">
                            {row.actorName}
                            <span className="text-muted/70"> · {ACTOR_ROLE_LABEL[row.actorRole]}</span>
                          </p>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>

              <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted">
                <p>
                  Showing{" "}
                  <span className="font-medium text-slate-700">{rows.length}</span>{" "}
                  of <span className="font-medium text-slate-700">{serverTotal}</span> events
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
            </>
          )}
        </div>
      </div>

      <AuditLogDetailsDrawer
        open={drawerOpen}
        row={drawerRow}
        onClose={closeDrawer}
        onViewTicket={handleViewTicket}
      />
    </AppLayout>
  );
}
