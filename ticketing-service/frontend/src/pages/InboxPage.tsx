import { AppLayout } from "@/components/layout/AppLayout";
import { AgentInbox } from "@/components/inbox/AgentInbox";
import { EmailDetails } from "@/components/inbox/EmailDetails";
import { InboxActionsPanel } from "@/components/inbox/InboxActionsPanel";

export function InboxPage() {
  return (
    <AppLayout
      title="Inbox"
      description="Emails waiting for an agent decision."
    >
      {/* Viewport-relative heights on mobile/tablet (rather than
          fixed pixels) so the three stacked panels scale with the
          actual device instead of adding up to a fixed ~1260px that
          overshoots short phone screens. */}
      <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-9.5rem)] lg:grid-cols-[320px_1fr_300px]">
        <div className="h-[65vh] min-h-[360px] lg:h-full">
          <AgentInbox />
        </div>
        <div className="h-[50vh] min-h-[280px] lg:h-full">
          <EmailDetails />
        </div>
        <div className="h-[40vh] min-h-[220px] lg:h-full">
          <InboxActionsPanel />
        </div>
      </div>
    </AppLayout>
  );
}
