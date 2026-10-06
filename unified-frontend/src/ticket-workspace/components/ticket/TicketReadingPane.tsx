import { useCallback, useEffect, useRef, useState } from "react";
import { Lock } from "lucide-react";
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { EmptyState } from "@tw/components/common/EmptyState";
import { TicketHeader } from "@tw/components/ticket/TicketHeader";
import { TicketConversationFeed } from "@tw/components/ticket/TicketConversationFeed";
import { TicketAttachmentsTab } from "@tw/components/ticket/TicketAttachmentsTab";
import { TicketComposer } from "@tw/components/ticket/TicketComposer";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getTicket } from "@tw/api/ticket";
import { getTicketTimeline } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

interface TicketReadingPaneProps {
  ticketId: string;
}

// Outlook-style reading pane for a selected ticket — header (subject,
// ticket number, Back/Refresh/Change-Status/Change-Priority/Claim/
// More▼ actions, all reused as-is from TicketHeader.tsx/TicketActions.tsx),
// the conversation thread, attachments, and an always-visible inline
// Reply composer at the bottom. Deliberately does NOT render
// TicketPropertiesCard/SlaCard (the mockup's excluded "Ticket Details"
// side panel) — this is a straight port of TicketDetailPage.tsx's own
// fetch logic, minus that panel.
export function TicketReadingPane({ ticketId }: TicketReadingPaneProps) {
  const { activeTicket, setActiveTicket, timeline, setTimeline } = useWorkflowContext();
  const timelineRequestIdRef = useRef(0);
  const ticketRequestIdRef = useRef(0);

  const { run: runGetTicket, isLoading: isLoadingTicket } = useApiAction(getTicket);
  const { run: runGetTimeline } = useApiAction(getTicketTimeline);
  const [isHiding] = useState(false);

  const refreshTimeline = useCallback(async () => {
    const requestId = ++timelineRequestIdRef.current;
    const items = await runGetTimeline(ticketId);
    if (requestId !== timelineRequestIdRef.current) return;
    if (items) setTimeline(items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, runGetTimeline, setTimeline]);

  const refreshAll = useCallback(async () => {
    const requestId = ++ticketRequestIdRef.current;
    refreshTimeline();
    const ticket = await runGetTicket(ticketId);
    if (requestId !== ticketRequestIdRef.current) return;
    setActiveTicket(ticket);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  const hasCurrentTicket = !!activeTicket && activeTicket.ticket_id === ticketId;
  const initialLoading = isLoadingTicket && !hasCurrentTicket;
  const notFound = !isLoadingTicket && !hasCurrentTicket;

  if (initialLoading) {
    return <WorkflowLoader loading size={48} className="flex h-full items-center justify-center" />;
  }

  if (notFound || !activeTicket) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          icon="🎫"
          title="Ticket not found or not yours"
          description="It may be assigned to a different agent, or the ID is wrong."
        />
      </div>
    );
  }

  const isFrozenByEscalation = !!activeTicket.escalation_pending_acceptance;

  return (
    <div className="flex h-full min-w-0 flex-col overflow-y-auto">
      <div className="flex flex-col gap-4 border-b border-border p-4">
        <TicketHeader
          ticket={activeTicket}
          onActionComplete={refreshAll}
          onRefresh={refreshAll}
          isRefreshing={isLoadingTicket}
        />
        <p className="text-[12px] text-muted">
          {activeTicket.client_company_name ?? activeTicket.client_name ?? "Unknown client"}
          {activeTicket.agent_name ? ` → ${activeTicket.agent_name}` : " → Unassigned"}
        </p>
        {activeTicket.current_status === "CLOSED" && (
          <div className="flex items-center gap-2 rounded-md2 border border-border bg-canvas/60 px-3 py-2 text-[12px] text-slate-700">
            <Lock size={13} className="flex-none text-muted" />
            This ticket is closed. Reopen it to make further changes.
          </div>
        )}
      </div>

      <div className="flex-1 p-4">
        <TicketConversationFeed events={timeline} isHiding={isHiding} />
      </div>

      <div className="border-t border-border p-4">
        <TicketAttachmentsTab onChanged={refreshTimeline} flat />
      </div>

      <div className="border-t border-border p-4">
        {isFrozenByEscalation ? (
          <p className="text-[12px] text-muted">
            This ticket has been escalated and is awaiting acknowledgment — it cannot be
            replied to until a supervisor acknowledges and reassigns it.
          </p>
        ) : (
          <TicketComposer
            key={activeTicket.ticket_id}
            mode="reply"
            lockMode
            flat
            onClose={() => {}}
            onSent={refreshTimeline}
          />
        )}
      </div>
    </div>
  );
}
