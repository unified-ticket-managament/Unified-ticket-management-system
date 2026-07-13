import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { EmptyState } from "@tw/components/common/EmptyState";
import { TicketHeader } from "@tw/components/ticket/TicketHeader";
import { TicketActivityPanel, type ActivityTab } from "@tw/components/ticket/TicketActivityPanel";
import { TicketComposer, type ComposerMode } from "@tw/components/ticket/TicketComposer";
import { TicketDetails } from "@tw/components/ticket/TicketDetails";
import { TicketActions } from "@tw/components/ticket/TicketActions";
import { EditAccessPanel } from "@tw/components/ticket/EditAccessPanel";
import { SlaCard } from "@tw/components/sla/SlaCard";
import { SlaTimeline } from "@tw/components/sla/SlaTimeline";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getTicket, listEditAccessRequests } from "@tw/api/ticket";
import { getTicketTimeline } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { activeTicket, setActiveTicket, setTimeline, setEditAccessRequests } =
    useWorkflowContext();
  const [composerMode, setComposerMode] = useState<ComposerMode | null>(null);
  const [activityTab, setActivityTab] = useState<ActivityTab>("timeline");
  // Bumped after any refresh so the Audit Log tab refetches
  // immediately instead of waiting for its own poll interval — only
  // while that tab is actually the one open, so an action taken with
  // Timeline showing doesn't force an Audit Log fetch nobody's
  // looking at yet (it'll fetch fresh on its own next mount).
  const [auditRefreshToken, setAuditRefreshToken] = useState(0);
  const activityTabRef = useRef(activityTab);
  activityTabRef.current = activityTab;
  // Guards against a fast ticketId change (or two overlapping manual
  // refreshes) racing: without this, an older ticket's/timeline's
  // response resolving after a newer one could overwrite the newer
  // data with stale data. Bumped once per refreshTimeline/refreshAll
  // call; a response is only applied if it's still the most recent
  // one requested.
  const timelineRequestIdRef = useRef(0);
  const ticketRequestIdRef = useRef(0);
  const editAccessRequestIdRef = useRef(0);

  const { run: runGetTicket, isLoading: isLoadingTicket } = useApiAction(getTicket);
  const { run: runGetTimeline } = useApiAction(getTicketTimeline);
  const { run: runListEditAccess } = useApiAction(listEditAccessRequests);

  const refreshTimeline = useCallback(async () => {
    if (!ticketId) return;
    const requestId = ++timelineRequestIdRef.current;
    const items = await runGetTimeline(ticketId);
    if (requestId !== timelineRequestIdRef.current) return;
    if (items) setTimeline(items);
    if (activityTabRef.current === "audit") {
      setAuditRefreshToken((token) => token + 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, runGetTimeline, setTimeline]);

  // Shared by TicketActions (reads the list to check for an active
  // approved grant) and EditAccessPanel (renders/manages it, and
  // calls this again after approve/reject/request) — one fetch here
  // instead of each component fetching its own copy independently.
  const refreshEditAccessRequests = useCallback(async () => {
    if (!ticketId) return;
    const requestId = ++editAccessRequestIdRef.current;
    const result = await runListEditAccess(ticketId);
    if (requestId !== editAccessRequestIdRef.current) return;
    if (result) setEditAccessRequests(result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, runListEditAccess, setEditAccessRequests]);

  const refreshAll = useCallback(async () => {
    if (!ticketId) return;
    const requestId = ++ticketRequestIdRef.current;
    // Independent, not awaited together — the ticket's own fields
    // (header, status/priority, actions) render the moment its fetch
    // resolves, instead of waiting on the timeline/edit-access
    // requests too. Both of those run in parallel on their own
    // schedule (each has its own request-id guard) and update their
    // own state whenever they finish, without holding up first paint
    // of everything else.
    refreshTimeline();
    refreshEditAccessRequests();
    const ticket = await runGetTicket(ticketId);
    if (requestId !== ticketRequestIdRef.current) return;
    // Explicitly clear on failure (e.g. transferred away from the
    // current agent) so the page drops to the empty state instead
    // of continuing to show stale, no-longer-accessible data.
    setActiveTicket(ticket);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  useEffect(() => {
    refreshAll();
    setComposerMode(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  const showEmptyState = !isLoadingTicket && (!activeTicket || activeTicket.ticket_id !== ticketId);

  return (
    <AppLayout
      title="Ticket"
      description="Every action taken here is recorded on the ticket's timeline."
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

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
              <div className="flex flex-col gap-5">
                <TicketActivityPanel
                  activeTab={activityTab}
                  onTabChange={setActivityTab}
                  onTimelineChanged={refreshTimeline}
                  auditRefreshToken={auditRefreshToken}
                />
                {composerMode && (
                  <TicketComposer
                    mode={composerMode}
                    onClose={() => setComposerMode(null)}
                    onSent={() => {
                      setComposerMode(null);
                      refreshTimeline();
                    }}
                  />
                )}
              </div>
              {/* The outer cell stretches to match the left column's
                  height (CSS Grid's default align-items: stretch) so
                  the inner sticky wrapper has room to float within it
                  instead of being pinned the moment it's scrolled —
                  sticky needs a taller ancestor to have any range of
                  motion. */}
              <div>
                <div className="flex flex-col gap-5 lg:sticky lg:top-0">
                  <TicketDetails onRelatedChanged={refreshAll} />
                  <SlaCard ticketId={activeTicket.ticket_id} ticketPriority={activeTicket.current_priority} />
                  <TicketActions onActionComplete={refreshAll} onOpenComposer={setComposerMode} />
                  <EditAccessPanel onRequestsChanged={refreshEditAccessRequests} />
                </div>
              </div>
            </div>
          </div>
        )
      )}
    </AppLayout>
  );
}
