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
      <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-9.5rem)] lg:grid-cols-[320px_1fr_300px]">
        <div className="h-[520px] lg:h-full">
          <AgentInbox />
        </div>
        <div className="h-[420px] lg:h-full">
          <EmailDetails />
        </div>
        <div className="h-[320px] lg:h-full">
          <InboxActionsPanel />
        </div>
      </div>
    </AppLayout>
  );
}
