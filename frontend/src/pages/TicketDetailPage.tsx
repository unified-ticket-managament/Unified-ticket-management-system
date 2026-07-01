import { useCallback, useEffect } from "react";
import { useParams } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { EmptyState } from "@/components/common/EmptyState";
import { TicketHeader } from "@/components/ticket/TicketHeader";
import { TicketActivityRail } from "@/components/ticket/TicketActivityRail";
import { TicketConversation } from "@/components/ticket/TicketConversation";
import { TicketDetails } from "@/components/ticket/TicketDetails";
import { TicketActions } from "@/components/ticket/TicketActions";
import { useApiAction } from "@/hooks/useApiAction";
import { getTicket } from "@/api/ticket";
import { getTicketTimeline } from "@/api/interaction";
import { useWorkflowContext } from "@/context/WorkflowContext";

export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { agentName, activeTicket, setActiveTicket, setTimeline } = useWorkflowContext();

  const { run: runGetTicket, isLoading: isLoadingTicket } = useApiAction(getTicket);
  const { run: runGetTimeline } = useApiAction(getTicketTimeline);

  const refreshTimeline = useCallback(async () => {
    if (!ticketId) return;
    const items = await runGetTimeline(ticketId, agentName);
    if (items) setTimeline(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, agentName, runGetTimeline, setTimeline]);

  const refreshAll = useCallback(async () => {
    if (!ticketId) return;
    const ticket = await runGetTicket(ticketId, agentName);
    // Explicitly clear on failure (e.g. transferred away from the
    // current agent) so the page drops to the empty state instead
    // of continuing to show stale, no-longer-accessible data.
    setActiveTicket(ticket);
    await refreshTimeline();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, agentName]);

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, agentName]);

  const showEmptyState = !isLoadingTicket && (!activeTicket || activeTicket.ticket_id !== ticketId);

  return (
    <AppLayout
      title="Ticket"
      description="Every action taken here is recorded on the ticket's conversation and activity feed."
    >
      {showEmptyState ? (
        <div className="rounded-md2 border border-border bg-surface shadow-xs">
          <EmptyState
            icon="🎫"
            title={isLoadingTicket ? "Loading ticket…" : "Ticket not found or not yours"}
            description={
              isLoadingTicket
                ? undefined
                : "It may be assigned to a different agent, or the ID is wrong."
            }
          />
        </div>
      ) : (
        activeTicket && (
          <div className="flex flex-col gap-5">
            <TicketHeader ticket={activeTicket} />

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr_320px]">
              <TicketActivityRail />
              <TicketConversation onChanged={refreshTimeline} />
              <div className="flex flex-col gap-5">
                <TicketDetails />
                <TicketActions onActionComplete={refreshAll} />
              </div>
            </div>
          </div>
        )
      )}
    </AppLayout>
  );
}
