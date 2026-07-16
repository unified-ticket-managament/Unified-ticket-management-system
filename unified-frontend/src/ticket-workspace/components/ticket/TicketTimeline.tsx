import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Card } from "@tw/components/common/Card";
import {
  InteractionDetailsDrawer,
  type InteractionDrawerRow,
} from "@tw/components/common/InteractionDetailsDrawer";
import { TicketConversationFeed } from "@tw/components/ticket/TicketConversationFeed";
import { RETIRED_INTERACTION_TYPES, summarize } from "@tw/lib/interactionMeta";
import { shortId } from "@tw/lib/format";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getInteractionThread, hideInteraction } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { InteractionResponse, ThreadResponse } from "@tw/types";

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
            Interactions
          </Link>
        )
      }
    >
      <TicketConversationFeed
        events={events}
        onHide={handleHide}
        isHiding={isHiding}
        onItemClick={handleEventClick}
      />
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
