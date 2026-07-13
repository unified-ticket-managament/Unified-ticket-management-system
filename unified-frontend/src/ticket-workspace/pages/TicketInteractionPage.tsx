import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { EmptyState } from "@tw/components/common/EmptyState";
import { TicketConversationFeed } from "@tw/components/ticket/TicketConversationFeed";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getTicket } from "@tw/api/ticket";
import { getTicketTimeline } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { shortId } from "@tw/lib/format";

// "Ticket Interaction" — the complete conversation history (incoming
// emails, outgoing replies, internal notes, attachment uploads) for
// one existing ticket, reached from that ticket's own "More" menu.
// Not a new ticket and not a new activity feed: it reuses the exact
// same GET /tickets/{id} + GET /tickets/{id}/interactions calls and
// the same TicketConversationFeed rendering the Timeline tab already
// uses — just as a dedicated full page instead of one tab among others.
export function TicketInteractionPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const navigate = useNavigate();
  const { activeTicket, setActiveTicket, timeline, setTimeline } = useWorkflowContext();

  const { run: runGetTicket, isLoading: isLoadingTicket } = useApiAction(getTicket);
  const { run: runGetTimeline, isLoading: isLoadingTimeline } = useApiAction(getTicketTimeline);

  useEffect(() => {
    if (!ticketId) return;
    runGetTicket(ticketId).then((ticket) => setActiveTicket(ticket));
    runGetTimeline(ticketId).then((items) => {
      if (items) setTimeline(items);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  const events = [...timeline].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  const isLoading = isLoadingTicket || isLoadingTimeline;
  const showEmptyState = !isLoading && (!activeTicket || activeTicket.ticket_id !== ticketId);

  return (
    <AppLayout>
      <div className="flex flex-col gap-5">
        <div>
          <button
            type="button"
            onClick={() => navigate(`/tickets/${ticketId}`)}
            className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
          >
            <ArrowLeft size={14} />
            Back
          </button>

          {!showEmptyState && activeTicket && (
            <>
              <p className="font-mono text-[11px] font-semibold tracking-wide text-accent">
                TKT-{shortId(activeTicket.ticket_id, 8)}
              </p>
              <h2 className="mt-1 text-2xl font-bold leading-tight text-slate-900">
                {activeTicket.title}
              </h2>
            </>
          )}
        </div>

        {showEmptyState ? (
          <div className="rounded-md2 border border-border bg-surface shadow-xs">
            <EmptyState
              icon="🎫"
              title={isLoading ? "Loading ticket…" : "Ticket not found or not yours"}
              description={
                isLoading ? undefined : "It may be assigned to a different agent, or the ID is wrong."
              }
            />
          </div>
        ) : (
          <div className="rounded-md2 border border-border bg-surface p-5 shadow-xs">
            <TicketConversationFeed events={events} />
          </div>
        )}
      </div>
    </AppLayout>
  );
}
