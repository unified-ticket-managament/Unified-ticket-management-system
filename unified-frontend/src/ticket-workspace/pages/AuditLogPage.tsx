import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Globe, Lock, RefreshCw, Search, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Badge } from "@tw/components/common/Badge";
import { ClientFilterSelect } from "@tw/components/common/ClientFilterSelect";
import { Button } from "@tw/components/common/Button";
import { AuditEventList } from "@/components/audit/AuditEventList";
import { AuditEventDetailsDrawer } from "@/components/audit/AuditEventDetailsDrawer";
import {
  normalizeTicketAuditEvent,
  type AuditFieldLookup,
  type TicketAuditEventInput,
} from "@/components/audit/normalizeAuditEvent";
import { CentralizedAuditLogPanel } from "@/components/audit/CentralizedAuditLogPanel";
import { getAllTicketAuditLogs } from "@tw/api/auditLog";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import { auditMetaFor } from "@tw/lib/auditLogMeta";
import { resolveClientFilterValue } from "@tw/lib/clientFilter";
import { isSupervisorRole } from "@/lib/role-access";
import type { AuditEntityType, AuditEventType } from "@tw/types";

type AuditRow = TicketAuditEventInput;

const ENTITY_TYPES: AuditEntityType[] = ["TICKET", "INTERACTION", "ATTACHMENT", "CLIENT", "USER"];
const EVENT_TYPES: AuditEventType[] = [
  "TICKET_CREATED",
  "TICKET_UPDATED",
  "TICKET_RESOLVED",
  "STATUS_CHANGED",
  "PRIORITY_CHANGED",
  "AGENT_TRANSFERRED",
  "CATEGORY_TRANSFERRED",
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
  const { agents, clients, categories } = useWorkflowContext();

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

  // A second, independent view mode — the genuinely system-wide
  // Centralized Audit Log (RBAC's own audit_logs table: logins, user/
  // role/permission/category changes, permission overrides/requests,
  // impersonation, Rule/Mail-Folder/SLA-Policy changes — see root
  // CLAUDE.md's audit-log separation section). Gated on audit:view,
  // completely independent of ticket:view_global_audit_log above —
  // holding one must never imply the other. Deliberately never called
  // "centralized" in this file's own variable names to avoid colliding
  // with centralizedMode/effectiveCentralized's unrelated, ticket-
  // domain "all clients' tickets" meaning.
  const canViewCentralized = (currentUser?.permissions ?? []).includes("audit:view");
  const [viewMode, setViewMode] = useState<"ticket" | "centralized">("ticket");

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
  const [clientFilter, setClientFilter] = useState("ALL");
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
        const { clientId, categoryName } = resolveClientFilterValue(clientFilter, categories);
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
          clientCompanyId: clientId,
          ticketType: categoryName,
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
          impersonatorName: log.impersonator_name ?? null,
          ticketId: log.ticket_id,
          ticketTitle: log.ticket_title,
          clientCompanyName: log.client_company_name,
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
    [entityFilter, eventFilter, agentFilter, clientFilter, categories, dateFrom, dateTo, debouncedSearch, effectiveCentralized]
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
        clientFilter,
        dateFrom,
        dateTo,
        effectiveCentralized,
      ]),
    [debouncedSearch, entityFilter, eventFilter, agentFilter, clientFilter, dateFrom, dateTo, effectiveCentralized]
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
      clientFilter !== "ALL" ||
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

  // Resolves the raw FK ids that show up in a diff's old/new_values
  // (agent_id, client_company_id, category_id, ...) to real names —
  // agents/clients/categories are already loaded here for the filter
  // dropdowns above, so this adds no extra fetch. See
  // normalizeAuditEvent.ts's own doc comment for why a not-found id
  // falls back to a short id rather than a fabricated name.
  const auditFieldLookup = useMemo<AuditFieldLookup>(
    () => ({
      agents: new Map(agents.map((a) => [a.user_id, a.name])),
      clients: new Map(clients.map((c) => [c.client_id, c.name])),
      categories: new Map(categories.map((c) => [c.category_id, c.category_name])),
    }),
    [agents, clients, categories]
  );

  // Presentation is entirely delegated to the shared AuditEventRow (via
  // AuditEventList) — this page only normalizes its own API rows into
  // the domain-agnostic UnifiedAuditEvent shape. See
  // normalizeAuditEvent.ts and the Centralized Audit Log's own
  // (symmetric) use of normalizeCentralizedAuditEvent.
  const normalizedEvents = useMemo(
    () => rows.map((row) => normalizeTicketAuditEvent(row, handleViewTicket, auditFieldLookup)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, auditFieldLookup]
  );

  const scopeDescription =
    viewMode === "centralized"
      ? "Immutable, system-wide record of every RBAC and ticket-management action."
      : isGlobalRole
        ? "Immutable record of every ticket change across the system."
        : effectiveCentralized
          ? "Immutable record of every ticket change for tickets assigned to you — ticket:view_global_audit_log does not grant company-wide visibility."
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
        canViewCentralized ? (
          <Button
            size="sm"
            variant={viewMode === "centralized" ? "primary" : "secondary"}
            className="gap-1.5"
            onClick={() => setViewMode((v) => (v === "centralized" ? "ticket" : "centralized"))}
          >
            <ShieldCheck size={14} />
            {viewMode === "centralized" ? "View Ticket Audit Log" : "View Centralized Audit Log"}
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4">
        {viewMode === "centralized" && (
          <div>
            <Badge tone="info">Centralized Audit View</Badge>
          </div>
        )}

        {viewMode === "centralized" ? (
          <CentralizedAuditLogPanel />
        ) : (
          <>
            {!isGlobalRole && centralizedMode && (
              <div>
                <Badge tone="info">My Assigned Tickets (Global)</Badge>
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

              <ClientFilterSelect
                clients={clients}
                categories={categories}
                value={clientFilter}
                onChange={setClientFilter}
              />

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

              {!isGlobalRole && (
                <Button
                  size="sm"
                  variant={centralizedMode ? "primary" : "secondary"}
                  className="gap-1.5"
                  disabled={!canViewGlobalAuditLog}
                  title={
                    canViewGlobalAuditLog
                      ? "Shows tickets assigned to you specifically — not every client's tickets."
                      : "You don't have permission to view this."
                  }
                  onClick={() => setCentralizedMode((v) => !v)}
                >
                  <Globe size={14} />
                  {centralizedMode ? "Back to My Ticket Scope" : "Show My Assigned Tickets (Global)"}
                </Button>
              )}

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

            <AuditEventList
              events={normalizedEvents}
              isLoading={isLoading}
              onEventClick={(event) => {
                const row = rows.find((r) => r.auditId === event.id);
                if (row) handleRowClick(row);
              }}
              emptyTitle={!hasActiveFilters && page === 1 ? "No audit events yet" : "No audit events found"}
              emptyDescription={
                !hasActiveFilters && page === 1
                  ? "Ticket changes will appear here permanently once they happen."
                  : "Try adjusting your filters."
              }
              footer={
                <div className="flex items-center justify-between">
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
              }
            />
          </>
        )}
      </div>

      <AuditEventDetailsDrawer
        open={drawerOpen}
        event={drawerRow ? normalizeTicketAuditEvent(drawerRow, handleViewTicket, auditFieldLookup) : null}
        onClose={closeDrawer}
      />
    </AppLayout>
  );
}
