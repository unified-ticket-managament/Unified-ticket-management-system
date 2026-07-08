import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { EmptyState } from "@tw/components/common/EmptyState";
import { TicketHeader } from "@tw/components/ticket/TicketHeader";
import { TicketActivityPanel, type ActivityTab } from "@tw/components/ticket/TicketActivityPanel";
import { TicketComposer, type ComposerMode } from "@tw/components/ticket/TicketComposer";
import { TicketDetails } from "@tw/components/ticket/TicketDetails";
import { TicketActions } from "@tw/components/ticket/TicketActions";
import { useApiAction } from "@tw/hooks/useApiAction";
import { getTicket } from "@tw/api/ticket";
import { getTicketTimeline } from "@tw/api/interaction";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

export function TicketDetailPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { activeTicket, setActiveTicket, setTimeline } = useWorkflowContext();
  const [composerMode, setComposerMode] = useState<ComposerMode | null>(null);
  const [activityTab, setActivityTab] = useState<ActivityTab>("timeline");
  // Bumped after any refresh so the Audit Log tab refetches
  // immediately instead of waiting for its own poll interval.
  const [auditRefreshToken, setAuditRefreshToken] = useState(0);

  const { run: runGetTicket, isLoading: isLoadingTicket } = useApiAction(getTicket);
  const { run: runGetTimeline } = useApiAction(getTicketTimeline);

  const refreshTimeline = useCallback(async () => {
    if (!ticketId) return;
    const items = await runGetTimeline(ticketId);
    if (items) setTimeline(items);
    setAuditRefreshToken((token) => token + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, runGetTimeline, setTimeline]);

  const refreshAll = useCallback(async () => {
    if (!ticketId) return;
    const ticket = await runGetTicket(ticketId);
    // Explicitly clear on failure (e.g. transferred away from the
    // current agent) so the page drops to the empty state instead
    // of continuing to show stale, no-longer-accessible data.
    setActiveTicket(ticket);
    await refreshTimeline();
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
                  <TicketActions onActionComplete={refreshAll} onOpenComposer={setComposerMode} />
                </div>
              </div>
            </div>
          </div>
        )
      )}
    </AppLayout>
  );
}
