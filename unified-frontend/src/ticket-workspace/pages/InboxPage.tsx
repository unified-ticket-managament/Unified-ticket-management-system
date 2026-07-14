"use client";

import { useCallback, useState } from "react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { ComposeView, type ComposeInitialValues } from "@tw/components/mail/ComposeView";
import { MailSidebar } from "@tw/components/mail/MailSidebar";
import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import { MessageList } from "@tw/components/mail/MessageList";
import { SystemMailDetailsView } from "@tw/components/mail/SystemMailDetailsView";
import { SystemMailList } from "@tw/components/mail/SystemMailList";
import { useMailInbox, type MailViewKey } from "@tw/hooks/useMailInbox";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

const VIEW_LABELS: Record<MailViewKey, string> = {
  pending: "Inbox",
  unassigned: "Unassigned",
  mine: "My Claims",
  sent: "Sent",
  drafts: "Drafts",
  replied: "Replied",
  ticketed: "Ticketed",
  archived: "Archived",
  all: "All Inboxes",
  system: "System",
};

// The entire Mail page: a fixed left folder sidebar and a dynamic
// right content area with exactly three views (Message List, Message
// Details, Compose), switched only via client-side state here — never
// navigation, a modal, or a second panel. `useMailInbox` is still
// owned exactly once, at the top of the page (see its own docstring
// for why), and every child below is a plain, mostly-presentational
// consumer of it.
export function InboxPage() {
  const mail = useMailInbox();
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const [composeOpen, setComposeOpen] = useState(false);
  const [composeInitialValues, setComposeInitialValues] = useState<ComposeInitialValues | undefined>(undefined);

  // useCallback below (rather than plain function declarations) is
  // required for MailSidebar's React.memo to actually skip re-renders
  // — an unstable prop identity defeats memo regardless of how the
  // component itself is wrapped.
  const openCompose = useCallback(
    (initial?: ComposeInitialValues) => {
      setSelectedEmail(null);
      setComposeInitialValues(initial);
      setComposeOpen(true);
    },
    [setSelectedEmail]
  );

  const handleComposeClick = useCallback(() => openCompose(), [openCompose]);

  function closeCompose() {
    setComposeOpen(false);
    setComposeInitialValues(undefined);
  }

  const handleSelectView = useCallback(
    (view: MailViewKey) => {
      setComposeOpen(false);
      setSelectedEmail(null);
      mail.setActiveView(view);
    },
    [setSelectedEmail, mail.setActiveView]
  );

  const handleSelectFolder = useCallback(
    (folderId: string | null) => {
      setComposeOpen(false);
      setSelectedEmail(null);
      mail.setActiveFolder(folderId);
    },
    [setSelectedEmail, mail.setActiveFolder]
  );

  const handleSelectCategory = useCallback(
    (category: string | null) => {
      setComposeOpen(false);
      setSelectedEmail(null);
      mail.setActiveCategory(category);
    },
    [setSelectedEmail, mail.setActiveCategory]
  );

  async function handleOpen(interactionId: string) {
    setComposeOpen(false);
    await mail.openThread(interactionId);
  }

  function handleForward(values: { clientId: string | null; toEmail: string; subject: string; bodyHtml: string }) {
    openCompose({
      clientId: values.clientId ?? undefined,
      toEmail: values.toEmail,
      subject: values.subject,
      bodyHtml: values.bodyHtml,
    });
  }

  async function handleComposeSend(payload: {
    clientId: string;
    toEmail: string;
    subject: string;
    message: string;
    cc: string[];
    bcc: string[];
    files: File[];
  }) {
    const result = await mail.composeEmail(payload);
    if (result) closeCompose();
    return result;
  }

  const folderLabelBase = mail.activeCategory
    ? mail.activeCategory
    : mail.activeFolder
      ? mail.folders.find((f) => f.folder_id === mail.activeFolder)?.name ?? "Folder"
      : VIEW_LABELS[mail.activeView];
  const folderCount = mail.activeCategory
    ? mail.categoryCounts[mail.activeCategory] ?? 0
    : mail.activeFolder
      ? mail.folderCounts[mail.activeFolder] ?? 0
      : mail.viewCounts[mail.activeView] ?? 0;
  const folderLabel = `${folderLabelBase} (${folderCount})`;

  return (
    <AppLayout>
      {/* No title passed above (per Mail spec: no page header) — the
          top navbar (h-16) + main's own p-6 padding are the only other
          chrome, so no gap is left where the removed header used to be.
          Scrolling model: MailSidebar and MessageList each own a fixed,
          viewport-relative height (calc(100vh-7rem), matching that
          chrome) with their own internal scrollbar — the sidebar via
          `sticky` so it stays put as the page scrolls, the list via a
          plain bounded height. MessageDetailsView/ComposeView are
          deliberately left auto-height (no clamp) so a long thread or a
          tall reply composer just grows the page instead of being
          clipped — `main`'s own overflow-y-auto (shared with every
          other page) is what scrolls in that case. */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <MailSidebar
          activeView={mail.activeView}
          isComposing={composeOpen}
          onSelectView={handleSelectView}
          onCompose={handleComposeClick}
          counts={mail.viewCounts}
          isSupervisor={mail.isSupervisor}
          folders={mail.folders}
          folderCounts={mail.folderCounts}
          activeFolder={mail.activeFolder}
          onSelectFolder={handleSelectFolder}
          onCreateFolder={mail.createFolder}
          onDeleteFolder={mail.deleteFolder}
          categories={mail.categories}
          categoryCounts={mail.categoryCounts}
          activeCategory={mail.activeCategory}
          onSelectCategory={handleSelectCategory}
        />

        <div className="min-h-[560px] min-w-0 flex-1">
          {composeOpen ? (
            <ComposeView
              clients={mail.clients}
              initialValues={composeInitialValues}
              isSending={mail.isComposing}
              onSend={handleComposeSend}
              onDiscard={closeCompose}
            />
          ) : mail.activeView === "system" ? (
            mail.selectedSystemNotification ? (
              <SystemMailDetailsView
                notification={mail.selectedSystemNotification}
                onBack={mail.clearSelectedSystemNotification}
                onMarkRead={mail.markSystemNotificationRead}
              />
            ) : (
              <SystemMailList
                items={mail.systemNotifications}
                isLoading={mail.isSystemLoading}
                onOpen={mail.selectSystemNotification}
                onRefresh={mail.refresh}
              />
            )
          ) : selectedEmail ? (
            <MessageDetailsView
              email={selectedEmail}
              folders={mail.folders}
              isSupervisor={mail.isSupervisor}
              onBack={() => setSelectedEmail(null)}
              onRefreshList={mail.refresh}
              onForward={handleForward}
              onSaveDraft={mail.saveDraftMessage}
              onSendDraft={mail.sendDraftMessage}
              onDiscardDraft={mail.discardDraftMessage}
              onUploadDraftAttachment={mail.uploadDraftAttachment}
              onRemoveDraftAttachment={mail.removeDraftAttachment}
              onUpdateTags={mail.updateTags}
              onAssignFolder={mail.assignFolder}
            />
          ) : (
            <MessageList
              folderLabel={folderLabel}
              items={mail.filteredItems}
              isLoading={mail.isLoading}
              openingId={mail.openingId}
              openedIds={mail.openedIds}
              search={mail.search}
              onSearchChange={mail.setSearch}
              timeFilter={mail.timeFilter}
              onTimeFilterChange={mail.setTimeFilter}
              clientFilter={mail.clientFilter}
              onClientFilterChange={mail.setClientFilter}
              priorityFilter={mail.priorityFilter}
              onPriorityFilterChange={mail.setPriorityFilter}
              categoryFilter={mail.messageCategoryFilter}
              onCategoryFilterChange={mail.setMessageCategoryFilter}
              availableCategories={mail.categories}
              clients={mail.clients}
              onOpen={handleOpen}
              onCompose={handleComposeClick}
              onRefresh={mail.refresh}
              hasMore={mail.hasMore}
              onLoadMore={mail.loadMore}
            />
          )}
        </div>
      </div>
    </AppLayout>
  );
}
