import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { EyeOff, Search, SlidersHorizontal, X } from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { Modal } from "@/components/common/Modal";
import { SkeletonRows } from "@/components/common/Skeleton";
import { AGENTS } from "@/lib/agents";
import { getAgentInbox, openEmail } from "@/api/agent";
import { listTickets } from "@/api/ticket";
import { getTicketTimeline, hideInteractionById } from "@/api/interaction";
import { useApiAction } from "@/hooks/useApiAction";
import { useToast } from "@/context/ToastContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import { shortId, formatDateTime } from "@/lib/format";
import { metaFor, summarize } from "@/lib/interactionMeta";
import type { InteractionDirection, InteractionResponse, InteractionStatus, OpenEmailResponse } from "@/types";

interface InteractionRow {
  id: string;
  createdAt: string;
  type: string;
  direction: InteractionDirection;
  status: InteractionStatus;
  agent: string;
  ticketId: string | null;
  ticketTitle: string | null;
  clientName: string | null;
  summaryText: string;
  sourceAgent?: string;
}

const DIRECTIONS: InteractionDirection[] = ["INBOUND", "OUTBOUND", "INTERNAL"];
const STATUSES: InteractionStatus[] = ["PENDING", "ASSIGNED", "IGNORED"];

const selectClass =
  "rounded-md2 border border-border bg-white px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function InteractionsPage() {
  const navigate = useNavigate();
  const { pushToast } = useToast();
  const { agentName } = useWorkflowContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const ticketIdParam = searchParams.get("ticketId");

  const [rows, setRows] = useState<InteractionRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [directionFilter, setDirectionFilter] = useState<InteractionDirection | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<InteractionStatus | "ALL">("ALL");
  const [agentFilter, setAgentFilter] = useState("ALL");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [previewEmail, setPreviewEmail] = useState<OpenEmailResponse | null>(null);
  const { run: runOpenEmail } = useApiAction(openEmail);
  const { run: runHide, isLoading: isHiding } = useApiAction(hideInteractionById, {
    successMessage: "Interaction hidden.",
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      try {
        // Scoped to tickets this agent can see (their assignments,
        // plus anything still unassigned) — matches ticket-level
        // visibility rules so interactions never leak across agents.
        const tickets = await listTickets(agentName);
        const ticketRows = (
          await Promise.all(
            tickets.map(async (ticket) => {
              const timeline = await getTicketTimeline(ticket.ticket_id, agentName);
              return timeline.map<InteractionRow>((item: InteractionResponse) => ({
                id: item.interaction_id,
                createdAt: item.created_at,
                type: item.interaction_type,
                direction: item.direction,
                status: item.status,
                agent: item.performed_by ? shortId(item.performed_by) : "—",
                ticketId: ticket.ticket_id,
                ticketTitle: ticket.title,
                clientName: ticket.client_name,
                summaryText: summarize(item),
              }));
            })
          )
        ).flat();

        const inbox = await getAgentInbox(agentName);
        const pendingRows: InteractionRow[] = inbox.items.map((item) => ({
          id: item.interaction_id,
          createdAt: item.received_at,
          type: "EMAIL",
          direction: "INBOUND" as InteractionDirection,
          status: item.status,
          agent: agentName,
          ticketId: null,
          ticketTitle: null,
          clientName: item.client_name,
          summaryText: item.subject,
          sourceAgent: agentName,
        }));

        if (cancelled) return;
        const merged = [...pendingRows, ...ticketRows].sort(
          (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        );
        setRows(merged);
      } catch (error) {
        pushToast(
          error instanceof Error ? error.message : "Failed to load interactions.",
          "error"
        );
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  const types = useMemo(() => Array.from(new Set(rows.map((r) => r.type))).sort(), [rows]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (ticketIdParam && r.ticketId !== ticketIdParam) return false;
      if (
        term &&
        !r.summaryText.toLowerCase().includes(term) &&
        !(r.ticketTitle ?? "").toLowerCase().includes(term) &&
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
  }, [rows, ticketIdParam, search, typeFilter, directionFilter, statusFilter, agentFilter, dateFrom, dateTo]);

  const filteredTicketTitle = useMemo(() => {
    if (!ticketIdParam) return null;
    return rows.find((r) => r.ticketId === ticketIdParam)?.ticketTitle ?? null;
  }, [rows, ticketIdParam]);

  async function handleRowClick(row: InteractionRow) {
    if (row.ticketId) {
      navigate(`/tickets/${row.ticketId}`);
      return;
    }
    if (row.sourceAgent) {
      const detail = await runOpenEmail(row.sourceAgent, row.id);
      if (detail) setPreviewEmail(detail);
    }
  }

  async function handleHide(row: InteractionRow, e: React.MouseEvent) {
    e.stopPropagation();
    const result = await runHide(row.id, { removed_by: null });
    if (result) {
      setRows((prev) => prev.filter((r) => r.id !== row.id));
    }
  }

  return (
    <AppLayout
      title="Interactions"
      description={
        ticketIdParam
          ? "Interactions for this ticket."
          : `Emails and activity across tickets assigned to ${agentName}.`
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
              className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-sm text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-white focus:outline-none focus:ring-4 focus:ring-accent/10"
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
            {types.map((t) => (
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
            {AGENTS.map((a) => (
              <option key={a} value={a}>
                {a}
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

        <div className="rounded-md2 border border-border bg-surface shadow-xs">
          {isLoading ? (
            <div className="p-5">
              <SkeletonRows rows={6} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon="💬"
              title="No interactions found"
              description="Try adjusting your filters."
            />
          ) : (
            <ul className="divide-y divide-border">
              {filtered.map((row) => {
                const meta = metaFor(row.type);
                return (
                  <li key={row.id} className="group flex items-center transition-colors hover:bg-surfaceHover">
                    <button
                      onClick={() => handleRowClick(row)}
                      aria-label={`${meta.label}: ${row.summaryText}`}
                      className="flex flex-1 items-center gap-3.5 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
                    >
                      <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                        {meta.icon}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[13px] font-semibold text-slate-900">
                            {meta.label}
                          </p>
                          <Badge tone={meta.tone}>{row.direction}</Badge>
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
                        <p className="mt-1 truncate text-[13px] text-slate-600">{row.summaryText}</p>
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
          )}
        </div>
      </div>

      <Modal
        open={!!previewEmail}
        title="Email Preview"
        onClose={() => setPreviewEmail(null)}
        footer={
          <Button variant="secondary" size="sm" onClick={() => setPreviewEmail(null)}>
            Close
          </Button>
        }
      >
        {previewEmail && (
          <div className="flex flex-col gap-2 text-sm">
            <p className="font-semibold text-slate-900">{previewEmail.subject}</p>
            <p className="text-xs text-muted">
              From {previewEmail.from_email} ({previewEmail.client_name})
            </p>
            <p className="whitespace-pre-wrap text-slate-700">{previewEmail.body}</p>
          </div>
        )}
      </Modal>
    </AppLayout>
  );
}
