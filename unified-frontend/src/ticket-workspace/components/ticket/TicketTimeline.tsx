import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EyeOff } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import {
  InteractionDetailsDrawer,
  type InteractionDrawerRow,
} from "@tw/components/common/InteractionDetailsDrawer";
import { RETIRED_INTERACTION_TYPES, metaFor, summarize } from "@tw/lib/interactionMeta";
import { shortId } from "@tw/lib/format";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getInteractionThread, hideInteraction } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { InteractionResponse, ThreadResponse } from "@tw/types";

const toneRing: Record<string, string> = {
  default: "border-slate-200 bg-slate-50",
  success: "border-success/25 bg-success/10",
  warning: "border-warning/25 bg-warning/10",
  danger: "border-danger/25 bg-danger/10",
  info: "border-info/25 bg-info/10",
  accent: "border-accent/25 bg-accent/10",
};

const toneCard: Record<string, string> = {
  default: "border-border bg-canvas/60",
  success: "border-success/15 bg-success/5",
  warning: "border-warning/15 bg-warning/5",
  danger: "border-danger/15 bg-danger/5",
  info: "border-info/15 bg-info/5",
  accent: "border-accent/15 bg-accent/5",
};

interface TicketTimelineProps {
  onChanged: () => void;
  // Rendered inside TicketActivityPanel's tabbed box, which already
  // provides the outer border/shadow — see Card's `flat` prop.
  flat?: boolean;
}

export function TicketTimeline({ onChanged, flat = false }: TicketTimelineProps) {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { activeTicket, timeline } = useWorkflowContext();

  // Every interaction is already timestamped by the backend —
  // sort newest first rather than trusting call-site ordering.
  // Memoized so a re-render caused by an unrelated WorkflowContext
  // field changing (e.g. selectedEmail, from the Mail page) doesn't
  // re-sort this list every time.
  const events = useMemo(
    () =>
      [...timeline].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      ),
    [timeline]
  );

  const { run: runHide, isLoading: isHiding } = useApiAction(hideInteraction, {
    successMessage: "Interaction hidden.",
  });
  const { run: runGetThread, isLoading: isLoadingThread } = useApiAction(getInteractionThread);

  // Same request-generation guard as InteractionsPage.tsx's drawer —
  // a fast click from one event to another before the first thread
  // fetch resolves must not overwrite the drawer with the wrong
  // conversation.
  const drawerRequestIdRef = useRef(0);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerRow, setDrawerRow] = useState<InteractionDrawerRow | null>(null);
  const [drawerThread, setDrawerThread] = useState<ThreadResponse | null>(null);

  function toDrawerRow(item: InteractionResponse): InteractionDrawerRow {
    return {
      id: item.interaction_id,
      createdAt: item.created_at,
      type: item.interaction_type,
      direction: item.direction,
      status: item.status,
      ticketId: item.ticket_id,
      ticketTitle: activeTicket?.title ?? null,
      clientName: activeTicket?.client_company_name ?? null,
      agent: item.performed_by_name ?? (item.performed_by ? shortId(item.performed_by) : "—"),
      summaryText: summarize(item),
      raw: item,
    };
  }

  // Every ticket-linked event may be part of a thread (a reply, or a
  // root with replies already filed under it) — resolves to the full
  // conversation (parent + every descendant, any depth) via the same
  // GET /interactions/{id}/thread endpoint the Interactions page uses,
  // so a threaded email/reply clicked from this per-ticket Timeline
  // shows its complete parent/child context too, not just the one
  // clicked row. STATUS_CHANGE/PRIORITY_CHANGE/etc. are synthesized
  // audit rows, not real interactions with a thread — skip the fetch
  // for those and just show the single-item fallback view.
  async function handleEventClick(item: InteractionResponse) {
    const requestId = ++drawerRequestIdRef.current;
    setDrawerRow(toDrawerRow(item));
    setDrawerThread(null);
    setDrawerOpen(true);

    if (RETIRED_INTERACTION_TYPES.has(item.interaction_type)) {
      return;
    }

    const thread = await runGetThread(item.interaction_id);
    if (requestId !== drawerRequestIdRef.current) return;
    if (thread) setDrawerThread(thread);
  }

  function closeDrawer() {
    setDrawerOpen(false);
  }

  async function handleHide(interactionId: string) {
    if (!activeTicket) return;
    const result = await runHide(activeTicket.ticket_id, interactionId, {
      removed_by: null,
    });
    if (result) onChanged();
  }

  return (
    <>
    <Card
      flat={flat}
      title="Timeline"
      eyebrow={`${events.length} event${events.length === 1 ? "" : "s"}`}
      actions={
        ticketId && (
          <Link
            to={`/interactions?ticketId=${ticketId}`}
            className="text-[11px] font-semibold text-accent transition-colors hover:text-accent-700"
          >
            View all
          </Link>
        )
      }
    >
      {events.length === 0 ? (
        <EmptyState
          icon="🕒"
          title="No activity yet"
          description="Emails, replies, notes, status changes and uploads will appear here as they happen."
        />
      ) : (
        <ol className="flex flex-col gap-0">
          {events.map((item, index) => {
            const meta = metaFor(item.interaction_type);
            const isLast = index === events.length - 1;

            return (
              <li key={item.interaction_id} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={`flex h-8 w-8 flex-none items-center justify-center rounded-full border text-sm ${toneRing[meta.tone]}`}
                  >
                    {meta.icon}
                  </div>
                  {!isLast && <div className="w-px flex-1 bg-border" />}
                </div>

                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => handleEventClick(item)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") handleEventClick(item);
                  }}
                  className={`group flex-1 cursor-pointer rounded-md2 border p-4 pb-5 transition-colors hover:bg-surfaceHover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${toneCard[meta.tone]} ${
                    !item.is_visible ? "opacity-40" : ""
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-[13px] font-semibold text-slate-900">{meta.label}</p>
                      <Badge tone={meta.tone}>{item.direction}</Badge>
                      {!item.is_visible && <Badge tone="danger">hidden</Badge>}
                    </div>
                    <p className="text-[11px] font-medium text-muted">
                      {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>

                  <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                    {summarize(item)}
                  </p>

                  {item.attachments && item.attachments.length > 0 && (
                    <AttachmentList attachments={item.attachments} className="mt-2.5" />
                  )}

                  <div className="mt-2.5 flex items-center justify-between gap-2">
                    <p className="text-[11px] text-muted">
                      {item.performed_by
                        ? `Performed by ${item.performed_by_name ?? shortId(item.performed_by)}`
                        : ""}
                    </p>
                    {item.is_visible && !RETIRED_INTERACTION_TYPES.has(item.interaction_type) && (
                      <button
                        disabled={isHiding}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleHide(item.interaction_id);
                        }}
                        aria-label="Hide this interaction"
                        className="flex items-center gap-1 rounded-md2 text-[11px] font-medium text-muted opacity-0 transition-opacity hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30 disabled:opacity-50 group-hover:opacity-100"
                      >
                        <EyeOff size={12} /> Hide
                      </button>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
    <InteractionDetailsDrawer
      open={drawerOpen}
      row={drawerRow}
      thread={drawerThread}
      isLoadingThread={isLoadingThread}
      onClose={closeDrawer}
      onViewTicket={() => closeDrawer()}
    />
    </>
  );
}
