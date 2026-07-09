import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Lock, RefreshCw, Search, SlidersHorizontal } from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { AuditLogDetailsDrawer } from "@/components/common/AuditLogDetailsDrawer";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { getAllTicketAuditLogs } from "@/api/auditLog";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { formatDateTime } from "@/lib/format";
import { auditMetaFor, diffFields, formatFieldValue, humanizeFieldKey } from "@/lib/auditLogMeta";
import type { ActorRole, AuditEntityType, AuditEventType } from "@/types";

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

  const [rows, setRows] = useState<AuditRow[]>([]);
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
    async (showLoading: boolean) => {
      const requestId = ++requestIdRef.current;
      if (showLoading) setIsLoading(true);
      try {
        // Same visibility scoping as every other cross-ticket view in
        // this app (Interactions page, Inbox): this agent's tickets
        // plus anything still unassigned. One request for every
        // visible ticket's audit trail, instead of GET /tickets
        // followed by one GET .../audit-logs per ticket.
        const logs = await getAllTicketAuditLogs();

        // A newer load already started (agent switch, manual refresh,
        // or the next poll tick) — this response is stale, drop it
        // rather than overwriting fresher data with older data.
        if (requestId !== requestIdRef.current) return;

        const merged = logs
          .map<AuditRow>((log) => ({
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
          }))
          .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
        setRows(merged);
        setLoadError(null);
      } catch (error) {
        if (requestId !== requestIdRef.current) return;
        setLoadError(error instanceof Error ? error.message : "Failed to load audit logs.");
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    load(true);
    const interval = window.setInterval(() => load(false), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [load]);

  // Any filter change should snap back to page 1 — otherwise a
  // narrower result set can leave the user stranded on a page
  // number that no longer has any rows.
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, entityFilter, eventFilter, agentFilter, dateFrom, dateTo]);

  const filtered = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    return rows.filter((row) => {
      if (term && !row.ticketTitle.toLowerCase().includes(term)) return false;
      if (entityFilter !== "ALL" && row.entityType !== entityFilter) return false;
      if (eventFilter !== "ALL" && row.eventType !== eventFilter) return false;
      if (agentFilter !== "ALL" && row.actorName !== agentFilter) return false;
      if (dateFrom && new Date(row.createdAt) < new Date(dateFrom)) return false;
      if (dateTo && new Date(row.createdAt) > new Date(`${dateTo}T23:59:59`)) return false;
      return true;
    });
  }, [rows, debouncedSearch, entityFilter, eventFilter, agentFilter, dateFrom, dateTo]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pageItems = useMemo(
    () => filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [filtered, currentPage]
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

  return (
    <AppLayout
      title="Audit Log"
      description={`Immutable record of every ticket change across tickets assigned to ${currentUser?.name}.`}
    >
      <div className="flex flex-col gap-4">
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
            onClick={() => load(true)}
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
            <Button size="sm" variant="secondary" onClick={() => load(true)}>
              Retry
            </Button>
          </div>
        )}

        <div className="rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading && rows.length === 0 ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon="🔒"
              title={rows.length === 0 ? "No audit events yet" : "No audit events found"}
              description={
                rows.length === 0
                  ? "Ticket changes will appear here permanently once they happen."
                  : "Try adjusting your filters."
              }
            />
          ) : (
            <>
              <ul className="divide-y divide-border">
                {pageItems.map((row) => {
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
                  <span className="font-medium text-slate-700">
                    {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)}
                  </span>{" "}
                  of <span className="font-medium text-slate-700">{filtered.length}</span> events
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
