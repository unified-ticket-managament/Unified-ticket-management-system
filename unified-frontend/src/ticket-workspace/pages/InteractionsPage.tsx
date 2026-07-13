import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, EyeOff, Search, SlidersHorizontal, X } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { InteractionDetailsDrawer } from "@tw/components/common/InteractionDetailsDrawer";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { getInbox, openInboxThread } from "@tw/api/inbox";
import { getAllTicketInteractions, getInteractionThread, hideInteractionById } from "@tw/api/interaction";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { shortId, formatDateTime } from "@tw/lib/format";
import { RETIRED_INTERACTION_TYPES, metaFor, summarize } from "@tw/lib/interactionMeta";
import { isSupervisorRole } from "@/lib/role-access";
import type { InteractionDirection, InteractionResponse, InteractionStatus, OpenEmailResponse, ThreadResponse } from "@tw/types";

const PAGE_SIZE = 20;

// This cross-ticket activity explorer shows client communication
// only — inbound email, outbound replies, and internal notes.
// Everything else (status/priority changes, transfers, claims,
// edit-access requests, attachment uploads) stays on the ticket's
// own Timeline and Audit Log. Mirrored server-side (see the backend's
// INTERACTIONS_PAGE_VISIBLE_TYPES) now that filtering/pagination
// happens there instead of over a fully-loaded client-side array.
const INTERACTION_TYPE_OPTIONS = ["EMAIL", "REPLY", "INTERNAL_NOTE"];

interface InteractionRow {
  id: string;
  createdAt: string;
  type: string;
  direction: InteractionDirection;
  status: InteractionStatus;
  agent: string;
  // Raw `performed_by` id for ticket-linked rows only, kept alongside
  // the shortId-fallback `agent` above so the display name can be
  // upgraded to the real one once `agents` (fetched separately, async)
  // resolves — without that resolution being a dependency of the
  // network fetch itself (see the `ticketRows` memo below).
  performedById?: string | null;
  ticketId: string | null;
  ticketTitle: string | null;
  clientName: string | null;
  subject: string;
  summaryText: string;
  sourceAgent?: string;
  // Full backend record for ticket-linked rows — already returned by
  // the ticket timeline endpoint, so the drawer can render every
  // payload field without an extra request.
  raw?: InteractionResponse;
}

const DIRECTIONS: InteractionDirection[] = ["INBOUND", "OUTBOUND", "INTERNAL"];
const STATUSES: InteractionStatus[] = ["PENDING", "ASSIGNED", "IGNORED"];

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function InteractionsPage() {
  const navigate = useNavigate();
  const { currentUser } = useAuthContext();
  const { agents } = useWorkflowContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const ticketIdParam = searchParams.get("ticketId");

  // Raw ticket-linked rows for the current server page, before
  // agent-name resolution — see the `ticketRows` memo below for why
  // that's kept separate. `serverTotal` is the backend's filtered
  // (pre-pagination) total, from the paginated GET /tickets/interactions
  // call.
  const [rawTicketRows, setRawTicketRows] = useState<InteractionRow[]>([]);
  const [serverTotal, setServerTotal] = useState(0);
  // The (already small, self-bounded) pending inbox queue — fetched
  // unbounded every load, same as before pagination was added, and
  // filtered/merged in only on page 1 (see pageItems below) so it
  // never distorts the server-paginated ticket-linked total.
  const [rawPendingRows, setRawPendingRows] = useState<InteractionRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  // Separate generation counter for the independent pending-inbox
  // fetch below — kept apart from requestIdRef so the two fetches'
  // staleness checks can never cross-invalidate each other.
  const pendingRequestIdRef = useRef(0);
  // Aborts the previous in-flight /tickets/interactions request
  // whenever a newer one starts — covers both a real filter/page
  // change AND React Strict Mode's dev-only double-invoke of this
  // effect on mount (which would otherwise fire two full requests,
  // and thus two full backend query executions, for one visible
  // load). The stale request's response was already dropped by the
  // requestIdRef check below; this additionally stops the browser
  // from waiting on/transferring it and lets the backend see the
  // client disconnect rather than complete pointless work.
  const interactionsAbortRef = useRef<AbortController | null>(null);
  const inboxAbortRef = useRef<AbortController | null>(null);
  // Guards the drawer's own fetch (opened by clicking a row) against
  // a fast row-to-row selection change: without this, an older row's
  // thread/email response resolving after a newer row is already
  // selected could overwrite the drawer with the wrong conversation.
  const drawerRequestIdRef = useRef(0);

  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [directionFilter, setDirectionFilter] = useState<InteractionDirection | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<InteractionStatus | "ALL">("ALL");
  const [agentFilter, setAgentFilter] = useState("ALL");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<InteractionRow | null>(null);
  const [drawerEmail, setDrawerEmail] = useState<OpenEmailResponse | null>(null);
  const [drawerThread, setDrawerThread] = useState<ThreadResponse | null>(null);
  const { run: runOpenEmail, isLoading: isLoadingEmail } = useApiAction(openInboxThread);
  const { run: runGetThread, isLoading: isLoadingThread } = useApiAction(getInteractionThread);
  const { run: runHide, isLoading: isHiding } = useApiAction(hideInteractionById, {
    successMessage: "Interaction hidden.",
  });

  // Resolved as a value (not read from `agents` directly inside
  // `load`) so `load` only changes identity — and only re-fetches —
  // when the *selected* agent filter's id actually changes, not
  // whenever the (separately, asynchronously fetched) `agents` list
  // itself updates. `agentFilter` can't be set to a specific name
  // before `agents` has loaded (the dropdown options come from the
  // same list), so this stays `undefined` through the very first load.
  const agentId = useMemo(() => {
    if (agentFilter === "ALL") return undefined;
    return agents.find((a) => a.name === agentFilter)?.user_id;
  }, [agentFilter, agents]);

  // The critical path: fetches only the paginated, server-filtered
  // ticket-linked rows this tab actually needs to render. Previously
  // bundled into one Promise.all with getInbox() below — that made
  // the whole page wait on the unbounded pending-inbox queue just to
  // show 20 already-fetched rows. Split so this list renders the
  // moment its own (much cheaper, already-paginated) request
  // resolves; the pending queue now arrives independently and merges
  // in afterward wherever it's still visible (page 1 only).
  const loadInteractions = useCallback(
    async (pageToLoad: number) => {
      const requestId = ++requestIdRef.current;
      interactionsAbortRef.current?.abort();
      const controller = new AbortController();
      interactionsAbortRef.current = controller;
      setIsLoading(true);
      try {
        const offset = (pageToLoad - 1) * PAGE_SIZE;

        // Scoped to tickets this agent can see (their assignments,
        // plus anything still unassigned) — matches ticket-level
        // visibility rules so interactions never leak across agents.
        // Server-paginated/filtered now (see api/interaction.ts) —
        // this used to fetch every visible ticket's entire history in
        // one request and filter/paginate the whole thing client-side.
        const interactionsResult = await getAllTicketInteractions(
          {
            limit: PAGE_SIZE,
            offset,
            interactionType: typeFilter === "ALL" ? undefined : typeFilter,
            direction: directionFilter === "ALL" ? undefined : directionFilter,
            status: statusFilter === "ALL" ? undefined : statusFilter,
            agentId,
            ticketId: ticketIdParam ?? undefined,
            dateFrom: dateFrom ? new Date(dateFrom).toISOString() : undefined,
            dateTo: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
            search: debouncedSearch.trim() || undefined,
          },
          controller.signal
        );

        // A newer load already started (a filter/page change, or a
        // manual retry) — drop this now-stale response.
        if (requestId !== requestIdRef.current) return;

        const ticketRows = interactionsResult.items.map<InteractionRow>((item) => ({
          id: item.interaction_id,
          createdAt: item.created_at,
          type: item.interaction_type,
          direction: item.direction,
          status: item.status,
          // Resolved against `agents` in the `ticketRows` memo below,
          // once that (separately-fetched, async) list is available —
          // this shortId fallback is just the pre-resolution display
          // value, not a dependency of this fetch.
          agent: item.performed_by ? shortId(item.performed_by) : "—",
          performedById: item.performed_by,
          ticketId: item.ticket_id,
          ticketTitle: item.ticket_title,
          clientName: item.client_company_name,
          // Falls back to summarize() only for the rare row created
          // before `subject` existed and never backfilled (a
          // rootless legacy reply) — every new row always has one.
          subject: item.subject || summarize(item),
          summaryText: summarize(item),
          raw: item,
        }));

        setRawTicketRows(ticketRows);
        setServerTotal(interactionsResult.total);
        setLoadError(null);
      } catch (error) {
        if (requestId !== requestIdRef.current) return;
        // A real abort (Strict Mode's double-invoke, or a
        // filter/page change firing before this one finished) is not
        // a user-visible failure — only report a genuine error.
        if (error instanceof Error && error.name === "CanceledError") return;
        setLoadError(error instanceof Error ? error.message : "Failed to load interactions.");
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    },
    [typeFilter, directionFilter, statusFilter, agentId, ticketIdParam, dateFrom, dateTo, debouncedSearch]
  );

  // Secondary/non-essential: the still-pending (pre-ticket) queue,
  // only ever merged into page 1's view (see pageItems below) — a
  // single-ticket view or any page past the first has no use for it
  // at all, so skip the request entirely rather than fetch and
  // discard it. Bounded to PAGE_SIZE (it used to fetch the entire
  // unbounded pending queue just to enrich one page of 20 rows) and
  // runs independently of loadInteractions so a slow inbox fetch
  // never delays the ticket-linked rows from rendering.
  const loadPendingInbox = useCallback(
    async (pageToLoad: number) => {
      const requestId = ++pendingRequestIdRef.current;
      inboxAbortRef.current?.abort();
      const controller = new AbortController();
      inboxAbortRef.current = controller;

      if (pageToLoad !== 1 || ticketIdParam) {
        setRawPendingRows([]);
        return;
      }

      try {
        const inbox = await getInbox("pending", { limit: PAGE_SIZE }, controller.signal);
        if (requestId !== pendingRequestIdRef.current) return;

        const pendingRows: InteractionRow[] = inbox.items.map((item) => ({
          id: item.interaction_id,
          createdAt: item.received_at,
          type: "EMAIL",
          direction: "INBOUND" as InteractionDirection,
          status: item.status,
          agent: currentUser?.name ?? "—",
          ticketId: null,
          ticketTitle: null,
          clientName: item.client_name,
          subject: item.subject,
          summaryText: item.subject,
          sourceAgent: currentUser?.name,
        }));

        setRawPendingRows(pendingRows);
      } catch (error) {
        // Non-essential data — a failed/aborted fetch here silently
        // leaves the pending queue empty rather than surfacing an
        // error for what's still a successful page load overall.
      }
    },
    [ticketIdParam, currentUser]
  );

  // Drives every fetch: a page change (Next/Previous) or a filter
  // change, but never both as two separate round trips for one user
  // action. A filter change resets to page 1 — if we're not already
  // there, this effect only calls setPage(1) and returns (no fetch);
  // the resulting re-render changes `page`, re-runs this same effect,
  // and *that* pass does the actual fetch. Fetching unconditionally
  // here (the naive approach) would double-fetch: once for the old
  // page with the new filters, once more for page 1.
  const filterSignature = useMemo(
    () =>
      JSON.stringify([
        debouncedSearch,
        typeFilter,
        directionFilter,
        statusFilter,
        agentId,
        dateFrom,
        dateTo,
        ticketIdParam,
      ]),
    [debouncedSearch, typeFilter, directionFilter, statusFilter, agentId, dateFrom, dateTo, ticketIdParam]
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
    // Independent fetches, not a Promise.all — the (already fast,
    // server-paginated) ticket-linked rows render as soon as they
    // arrive, without waiting on the separate, non-essential pending-
    // inbox merge. Aborted correctly (see the abort-ref plumbing in
    // each function) if this effect re-fires before either resolves —
    // including React Strict Mode's dev-only double-invoke, which
    // would otherwise leave two full requests in flight for one
    // visible load.
    loadInteractions(page);
    loadPendingInbox(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSignature, page, loadInteractions, loadPendingInbox]);

  useEffect(() => {
    return () => {
      interactionsAbortRef.current?.abort();
      inboxAbortRef.current?.abort();
    };
  }, []);

  // Upgrades each ticket-linked row's shortId-fallback `agent` to the
  // real display name once `agents` (fetched independently, on its
  // own schedule, by WorkflowContext) resolves — purely an in-memory
  // recompute, not a re-fetch, so `load`/its effect never needs
  // `agents` as a dependency (that used to cause the interactions/
  // inbox fetch to fire twice on a cold mount: once before `agents`
  // arrived, once again the instant it did).
  const ticketRows = useMemo(() => {
    if (agents.length === 0) return rawTicketRows;
    const agentNameById = new Map(agents.map((a) => [a.user_id, a.name]));
    return rawTicketRows.map((r) =>
      r.performedById
        ? { ...r, agent: agentNameById.get(r.performedById) ?? shortId(r.performedById) }
        : r
    );
  }, [rawTicketRows, agents]);

  // The pending queue is small and already role-scoped (not the
  // unbounded historical log the ticket-linked side used to be), so
  // it stays filtered client-side rather than growing its own set of
  // server query params — see api/interaction.ts's search note for
  // the equivalent tradeoff on the ticket-linked side.
  const filteredPendingRows = useMemo(() => {
    if (ticketIdParam) return []; // pending rows never belong to a ticket
    const term = debouncedSearch.trim().toLowerCase();
    return rawPendingRows.filter((r) => {
      if (
        term &&
        !r.summaryText.toLowerCase().includes(term) &&
        !(r.clientName ?? "").toLowerCase().includes(term)
      ) {
        return false;
      }
      if (typeFilter !== "ALL" && r.type !== typeFilter) return false;
      if (directionFilter !== "ALL" && r.direction !== directionFilter) return false;
      if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
      if (agentFilter !== "ALL" && r.agent !== agentFilter) return false;
      if (dateFrom && new Date(r.createdAt) < new Date(dateFrom)) return false;
      if (dateTo && new Date(r.createdAt) > new Date(`${dateTo}T23:59:59`)) return false;
      return true;
    });
  }, [rawPendingRows, ticketIdParam, debouncedSearch, typeFilter, directionFilter, statusFilter, agentFilter, dateFrom, dateTo]);

  // The pending queue is only merged onto page 1 — it's additive on
  // top of the server-paginated ticket-linked rows, not itself paged,
  // so folding it into every page would both duplicate rows and throw
  // off "Page X of Y" (computed from the server's own filtered total).
  const pageItems = useMemo(() => {
    if (page !== 1) return ticketRows;
    return [...filteredPendingRows, ...ticketRows].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  }, [page, filteredPendingRows, ticketRows]);

  const totalCount = serverTotal + filteredPendingRows.length;
  const totalPages = Math.max(1, Math.ceil(serverTotal / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);

  const hasActiveFilters = Boolean(
    debouncedSearch.trim() ||
      typeFilter !== "ALL" ||
      directionFilter !== "ALL" ||
      statusFilter !== "ALL" ||
      agentFilter !== "ALL" ||
      dateFrom ||
      dateTo ||
      ticketIdParam
  );

  const filteredTicketTitle = useMemo(() => {
    if (!ticketIdParam) return null;
    return ticketRows.find((r) => r.ticketId === ticketIdParam)?.ticketTitle ?? null;
  }, [ticketRows, ticketIdParam]);

  async function handleRowClick(row: InteractionRow) {
    const requestId = ++drawerRequestIdRef.current;
    setDrawerRow(row);
    setDrawerEmail(null);
    setDrawerThread(null);
    setDrawerOpen(true);

    // Pending inbox rows only carry a summary until opened — fetch
    // the full email (same endpoint the inbox page already uses).
    if (!row.ticketId) {
      const detail = await runOpenEmail(row.id);
      if (requestId !== drawerRequestIdRef.current) return;
      if (detail) setDrawerEmail(detail);
      return;
    }

    // CLAIM/EDIT_ACCESS_* rows are synthesized from an audit-log
    // entry, not a real Interaction (see audit_to_interaction.py) —
    // row.id is that audit row's own id, which GET /interactions/{id}
    // /thread has never heard of. Skip the fetch; the drawer already
    // has everything it needs from the row itself (raw), same as any
    // other single-message, no-thread row.
    if (RETIRED_INTERACTION_TYPES.has(row.type)) {
      return;
    }

    // Any ticket-linked row may be part of a thread (a reply, or a
    // root with replies already filed under it) — always fetch the
    // full conversation so the drawer can show the parent and every
    // other reply, not just this one row's own fields. A row with no
    // real parent/children (a note, status change, etc.) still comes
    // back as a valid thread of exactly one message.
    const thread = await runGetThread(row.id);
    // A newer row click already started (the agent selected a
    // different row before this one's thread came back) — drop this
    // now-stale response rather than overwrite the drawer with the
    // wrong conversation.
    if (requestId !== drawerRequestIdRef.current) return;
    if (thread) setDrawerThread(thread);
  }

  function closeDrawer() {
    setDrawerOpen(false);
  }

  function handleViewTicket(ticketId: string) {
    setDrawerOpen(false);
    navigate(`/tickets/${ticketId}`);
  }

  async function handleHide(row: InteractionRow, e: React.MouseEvent) {
    e.stopPropagation();
    const result = await runHide(row.id, { removed_by: null });
    if (result) {
      setRawTicketRows((prev) => prev.filter((r) => r.id !== row.id));
      setRawPendingRows((prev) => prev.filter((r) => r.id !== row.id));
    }
  }

  return (
    <AppLayout
      title="Interactions"
      description={
        ticketIdParam
          ? "Interactions for this ticket."
          : isSupervisorRole(currentUser?.role)
            ? "Emails and activity across every ticket on the team."
            : `Emails and activity across tickets assigned to ${currentUser?.name}.`
      }
    >
      <div className="flex flex-col gap-4">
        {ticketIdParam && (
          <div className="flex items-center justify-between rounded-md2 border border-accent/25 bg-accent/5 px-4 py-3 text-xs text-slate-700 shadow-xs animate-fadeSlideIn">
            <span>
              Showing interactions for ticket{" "}
              <strong className="font-semibold text-slate-900">
                {filteredTicketTitle ?? shortId(ticketIdParam)}
              </strong>
            </span>
            <button
              onClick={() => setSearchParams({})}
              aria-label="Clear ticket filter"
              className="flex items-center gap-1 rounded-md2 font-semibold text-accent transition-colors hover:text-accent-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              <X size={13} /> Clear filter
            </button>
          </div>
        )}

        <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 rounded-md2 border border-border bg-surface p-3.5 shadow-xs">
          <div className="relative min-w-[240px] flex-1">
            <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search interactions by subject, sender, or client..."
              className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
          </div>

          <div className="hidden items-center gap-1.5 text-muted sm:flex">
            <SlidersHorizontal size={13} />
          </div>

          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            aria-label="Filter by interaction type"
            className={selectClass}
          >
            <option value="ALL">All Types</option>
            {INTERACTION_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {metaFor(t).label}
              </option>
            ))}
          </select>

          <select
            value={directionFilter}
            onChange={(e) => setDirectionFilter(e.target.value as InteractionDirection | "ALL")}
            aria-label="Filter by direction"
            className={selectClass}
          >
            <option value="ALL">All Directions</option>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as InteractionStatus | "ALL")}
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
        </div>

        {loadError && (
          <div className="flex items-center justify-between gap-3 rounded-md2 border border-danger/20 bg-danger/5 px-4 py-3 text-sm text-danger">
            <div className="flex items-center gap-2">
              <AlertTriangle size={15} className="flex-none" />
              <span>{loadError}</span>
            </div>
            <Button size="sm" variant="secondary" onClick={() => loadInteractions(page)}>
              Retry
            </Button>
          </div>
        )}

        <div className="rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading && pageItems.length === 0 ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : pageItems.length === 0 ? (
            <EmptyState
              icon="💬"
              title={!hasActiveFilters && page === 1 ? "No interactions yet" : "No interactions found"}
              description={
                !hasActiveFilters && page === 1
                  ? "Emails, replies, notes, and status changes will show up here."
                  : "Try adjusting your filters."
              }
            />
          ) : (
            <>
            <ul className="divide-y divide-border">
              {pageItems.map((row) => {
                const meta = metaFor(row.type);
                return (
                  <li key={row.id} className="group flex items-center transition-colors hover:bg-surfaceHover">
                    <button
                      onClick={() => handleRowClick(row)}
                      aria-label={`${row.subject}: ${row.summaryText}`}
                      className="flex flex-1 items-center gap-3.5 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
                    >
                      <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                        {meta.icon}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate text-[13px] font-semibold text-slate-900">
                            {row.subject}
                          </p>
                          <Badge tone={meta.tone}>{meta.label}</Badge>
                          {row.clientName && (
                            <span className="truncate text-xs text-muted">
                              {row.clientName}
                            </span>
                          )}
                          {row.ticketTitle && (
                            <span className="truncate text-xs text-muted">
                              on <span className="font-medium text-slate-500">{row.ticketTitle}</span>
                            </span>
                          )}
                        </div>
                        {/* For EMAIL rows summaryText IS the subject
                            (no body preview in this trimmed list
                            response) — skip the second line rather
                            than repeat the heading verbatim. */}
                        {row.summaryText && row.summaryText !== row.subject && (
                          <p className="mt-1 truncate text-[13px] text-slate-600">{row.summaryText}</p>
                        )}
                      </div>
                      <div className="flex-none text-right">
                        <p className="text-xs font-medium text-slate-600">{formatDateTime(row.createdAt)}</p>
                        <p className="mt-0.5 text-[11px] text-muted">{row.agent}</p>
                      </div>
                    </button>
                    <button
                      onClick={(e) => handleHide(row, e)}
                      disabled={isHiding}
                      title="Hide (soft delete) this interaction"
                      aria-label="Hide this interaction"
                      className="mr-4 flex h-9 w-9 flex-none items-center justify-center rounded-md2 text-muted opacity-0 transition-all hover:bg-danger/10 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30 group-hover:opacity-100 disabled:opacity-50"
                    >
                      <EyeOff size={15} />
                    </button>
                  </li>
                );
              })}
            </ul>

            <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted">
              <p>
                Showing{" "}
                <span className="font-medium text-slate-700">{pageItems.length}</span>{" "}
                of <span className="font-medium text-slate-700">{totalCount}</span> interactions
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

      <InteractionDetailsDrawer
        open={drawerOpen}
        row={drawerRow}
        email={drawerEmail}
        isLoadingEmail={isLoadingEmail}
        thread={drawerThread}
        isLoadingThread={isLoadingThread}
        onClose={closeDrawer}
        onViewTicket={handleViewTicket}
      />
    </AppLayout>
  );
}
