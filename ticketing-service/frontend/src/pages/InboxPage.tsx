import { AppLayout } from "@/components/layout/AppLayout";
import { AgentInbox } from "@/components/inbox/AgentInbox";
import { EmailDetails } from "@/components/inbox/EmailDetails";
import { InboxActionsPanel } from "@/components/inbox/InboxActionsPanel";
import { MailDetailsPanel } from "@/components/inbox/MailDetailsPanel";
import { MailSidebar } from "@/components/inbox/MailSidebar";
import { useMailInbox } from "@/hooks/useMailInbox";

export function InboxPage() {
  // Owned once here, not inside AgentInbox — MailSidebar and
  // AgentInbox both need the same view/counts/loading state, and
  // calling the hook in two places would mean two independent
  // fetches and two independently-drifting activeView states.
  const mail = useMailInbox();

  return (
    <AppLayout
      title="Mail"
      description="Emails waiting for an agent decision."
    >
      {/* Viewport-relative heights on mobile/tablet (rather than
          fixed pixels) so the stacked panels scale with the actual
          device instead of adding up to a fixed height that
          overshoots short phone screens. */}
      <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-9.5rem)] lg:grid-cols-[220px_300px_1fr_300px]">
        <div className="h-[30vh] min-h-[220px] lg:h-full">
          <MailSidebar
            activeView={mail.activeView}
            onSelectView={mail.setActiveView}
            counts={mail.viewCounts}
            isSupervisor={mail.isSupervisor}
            folders={mail.folders}
            folderCounts={mail.folderCounts}
            activeFolder={mail.activeFolder}
            onSelectFolder={mail.setActiveFolder}
            onCreateFolder={mail.createFolder}
            onDeleteFolder={mail.deleteFolder}
          />
        </div>
        <div className="h-[65vh] min-h-[360px] lg:h-full">
          <AgentInbox {...mail} />
        </div>
        <div className="h-[50vh] min-h-[280px] lg:h-full">
          <EmailDetails
            onSaveDraft={mail.saveDraftMessage}
            onSendDraft={mail.sendDraftMessage}
            onDiscardDraft={mail.discardDraftMessage}
          />
        </div>
        <div className="flex h-auto flex-col gap-4 lg:h-full lg:overflow-y-auto lg:scrollbar-thin">
          <MailDetailsPanel
            folders={mail.folders}
            onUpdateTags={mail.updateTags}
            onAssignFolder={mail.assignFolder}
            onSnooze={mail.snoozeItem}
            onUnsnooze={mail.unsnoozeItem}
          />
          <InboxActionsPanel />
        </div>
      </div>
    </AppLayout>
  );
}
