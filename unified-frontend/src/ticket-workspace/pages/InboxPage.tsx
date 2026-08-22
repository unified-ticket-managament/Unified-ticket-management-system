"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { ComposeView, type ComposeInitialValues } from "@tw/components/mail/ComposeView";
import { MailReadingPaneEmptyState } from "@tw/components/mail/MailReadingPaneEmptyState";
import { MailSidebar } from "@tw/components/mail/MailSidebar";
import { MailWorkspaceLayout } from "@tw/components/mail/MailWorkspaceLayout";
import { MessageDetailsView } from "@tw/components/mail/MessageDetailsView";
import { MessageList } from "@tw/components/mail/MessageList";
import { SystemMailDetailsView } from "@tw/components/mail/SystemMailDetailsView";
import { SystemMailList } from "@tw/components/mail/SystemMailList";
import { useIsDesktopViewport } from "@tw/hooks/useIsDesktopViewport";
import { useMailInbox, type MailViewKey } from "@tw/hooks/useMailInbox";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { useAuthContext } from "@tw/context/AuthContext";
import { RulesPanel } from "@/components/rules/RulesPanel";

const VIEW_LABELS: Record<MailViewKey, string> = {
  pending: "Inbox",
  unassigned: "Unassigned",
  mine: "My Tickets",
  sent: "Sent",
  drafts: "Drafts",
  replied: "Replied",
  ticketed: "Ticketed",
  archived: "Archived",
  all: "All Inboxes",
  system: "System",
};

// The entire Mail page. On desktop (see useIsDesktopViewport), this is
// an Outlook-style three-panel workspace — Mail Folders, Message
// List, and Message Details all visible and independently scrollable
// at once, resized via MailWorkspaceLayout's draggable dividers, with
// only Rules (not a mail list/detail pair at all) and Compose/message-
// selection swapping what Panel 3 shows. Below the `lg` breakpoint,
// this falls back to the original single dynamic content pane next to
// the folder sidebar, switching between exactly three views (Message
// List, Message Details, Compose) via client-side state — never
// navigation, a modal, or a second panel — since a resizable
// three-column layout isn't practical at that width. `useMailInbox` is
// still owned exactly once, at the top of the page (see its own
// docstring for why), and every child below is a plain, mostly-
// presentational consumer of it.
export function InboxPage() {
  const mail = useMailInbox();
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const isDesktop = useIsDesktopViewport();
  const [composeOpen, setComposeOpen] = useState(false);
  const [composeInitialValues, setComposeInitialValues] = useState<ComposeInitialValues | undefined>(undefined);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const canManageRules = (currentUser?.permissions ?? []).includes("rule:manage");

  // Rules lives inside this same mounted page (rulesOpen is a local
  // toggle, never a route change), so useMailInbox's own "load
  // folders once per mount" cache is never naturally invalidated by
  // creating/editing a rule's folder. Refetch folders specifically on
  // the true→false transition (leaving Rules) rather than on every
  // render or on every setRulesOpen(false) call site — this is the
  // one point in time folder state could actually have changed.
  const rulesWasOpenRef = useRef(false);
  useEffect(() => {
    if (rulesWasOpenRef.current && !rulesOpen) {
      mail.refreshFolders();
    }
    rulesWasOpenRef.current = rulesOpen;
  }, [rulesOpen, mail.refreshFolders]);

  // Tracks whatever message was open right before Compose/Forward
  // opened (openCompose always clears `selectedEmail`), so the Back
  // button on a Forward screen can return to it — a plain ref (not
  // state) so it never forces a re-render and openCompose's own
  // useCallback deps below stay untouched.
  const selectedEmailRef = useRef(selectedEmail);
  selectedEmailRef.current = selectedEmail;
  const previousEmailRef = useRef<typeof selectedEmail>(null);

  // useCallback below (rather than plain function declarations) is
  // required for MailSidebar's React.memo to actually skip re-renders
  // — an unstable prop identity defeats memo regardless of how the
  // component itself is wrapped.
  const openCompose = useCallback(
    (initial?: ComposeInitialValues) => {
      previousEmailRef.current = selectedEmailRef.current;
      setSelectedEmail(null);
      setComposeInitialValues(initial);
      setComposeOpen(true);
      setRulesOpen(false);
    },
    [setSelectedEmail]
  );

  const handleComposeClick = useCallback(() => openCompose(), [openCompose]);

  function closeCompose() {
    setComposeOpen(false);
    setComposeInitialValues(undefined);
  }

  // Forward-only "← Back": returns to the exact message being
  // forwarded (mailbox/selection/scroll all already preserved, since
  // this is a state swap, never a route change) instead of Discard's
  // "abandon and go to the inbox" behavior.
  function handleComposeBack() {
    closeCompose();
    setSelectedEmail(previousEmailRef.current);
  }

  const handleSelectView = useCallback(
    (view: MailViewKey) => {
      setComposeOpen(false);
      setRulesOpen(false);
      setSelectedEmail(null);
      mail.selectFolder(null);
      mail.setActiveView(view);
    },
    [setSelectedEmail, mail.setActiveView, mail.selectFolder]
  );

  const handleSelectFolder = useCallback(
    (folderId: string) => {
      setComposeOpen(false);
      setRulesOpen(false);
      setSelectedEmail(null);
      mail.selectFolder(folderId);
    },
    [setSelectedEmail, mail.selectFolder]
  );

  const handleOpenRules = useCallback(() => {
    setComposeOpen(false);
    setSelectedEmail(null);
    mail.selectFolder(null);
    setRulesOpen(true);
  }, [setSelectedEmail, mail.selectFolder]);

  async function handleOpen(interactionId: string) {
    setComposeOpen(false);
    setRulesOpen(false);
    await mail.openThread(interactionId);
  }

  // Refreshing an already-open message's details isn't "opening it
  // to read" — pass markRead: false so this never silently undoes an
  // explicit "Mark as Unread" on the message being refreshed.
  async function handleRefreshMessage(interactionId: string) {
    await mail.openThread(interactionId, { markRead: false });
  }

  // A First Response SLA notification (topbar bell or the Mail
  // "System" folder) links here as "/inbox?interaction_id=<id>" so
  // clicking it opens the specific message instead of leaving the
  // recipient to find it themselves — see sla_breach_notifier.py's
  // notify_first_response_threshold. The param is consumed once, then
  // cleared, so navigating away and back (or refreshing) doesn't
  // re-open it.
  useEffect(() => {
    const interactionId = searchParams.get("interaction_id");
    if (!interactionId) return;
    handleOpen(interactionId);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("interaction_id");
        return next;
      },
      { replace: true }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function handleForward(values: {
    clientId: string | null;
    toEmail: string;
    subject: string;
    bodyHtml: string;
    interactionId: string;
    originalAttachmentCount: number;
  }) {
    openCompose({
      clientId: values.clientId ?? undefined,
      toEmail: values.toEmail,
      subject: values.subject,
      bodyHtml: values.bodyHtml,
      mode: "forward",
      interactionId: values.interactionId,
      originalAttachmentCount: values.originalAttachmentCount,
    });
  }

  async function handleForwardSend(payload: {
    interactionId: string;
    clientId: string;
    recipientUserIds?: string[];
    recipientEmails?: string[];
    distributionListIds?: string[];
    cc?: string[];
    bcc?: string[];
    subject: string;
    message: string;
    files: File[];
    bodyHtml?: string;
    inlineImageInteractionIds?: string[];
  }) {
    const result = await mail.forwardToInternalUser(payload);
    if (result) closeCompose();
    return result;
  }

  async function handleComposeSend(payload: {
    clientId: string;
    toEmail?: string;
    subject: string;
    message: string;
    bodyHtml?: string;
    cc: string[];
    bcc: string[];
    files: File[];
    inlineImageInteractionIds?: string[];
    distributionListIds?: string[];
  }) {
    const result = await mail.composeEmail(payload);
    if (result) closeCompose();
    return result;
  }

  const folderLabel = `${VIEW_LABELS[mail.activeView]} (${mail.viewCounts[mail.activeView] ?? 0})`;

  function renderSidebar(variant: "standalone" | "panel") {
    return (
      <MailSidebar
        variant={variant}
        activeView={mail.activeView}
        isComposing={composeOpen}
        onSelectView={handleSelectView}
        onCompose={handleComposeClick}
        counts={mail.viewCounts}
        hideMyClaims={currentUser?.role === "Staff"}
        folders={mail.folders}
        folderCounts={mail.folderCounts}
        activeFolderId={mail.activeFolderId}
        onSelectFolder={handleSelectFolder}
        canManageRules={canManageRules}
        rulesActive={rulesOpen}
        onOpenRules={handleOpenRules}
      />
    );
  }

  // Panel 2 (Message List) for the desktop three-panel workspace —
  // deliberately independent of selectedEmail/selectedSystemNotification
  // so the list stays visible and browsable while Panel 3 shows a
  // message's details, Outlook-style (see MailWorkspaceLayout below).
  // Which list renders depends only on the active folder/view — the
  // exact same condition the original single-pane layout's own
  // ternary used for this half of its decision.
  const desktopListPanel = mail.activeFolderId ? (
    <MessageList
      variant="panel"
      selectedId={selectedEmail?.interaction_id ?? null}
      folderLabel={`${mail.folders.find((f) => f.folder_id === mail.activeFolderId)?.name.trim() ?? "Folder"} (${mail.folderRowsTotal})`}
      items={mail.folderRows}
      isLoading={mail.isFolderLoading}
      isError={mail.hasFolderError}
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
      hasMore={mail.folderRowsHasMore}
      onLoadMore={mail.loadMoreFolderRows}
    />
  ) : mail.activeView === "system" ? (
    <SystemMailList
      variant="panel"
      selectedId={mail.selectedSystemNotification?.notification_id ?? null}
      items={mail.systemNotifications}
      isLoading={mail.isSystemLoading}
      isError={mail.hasError}
      onOpen={mail.selectSystemNotification}
      onRefresh={mail.refresh}
    />
  ) : (
    <MessageList
      variant="panel"
      selectedId={selectedEmail?.interaction_id ?? null}
      folderLabel={folderLabel}
      items={mail.filteredItems}
      isLoading={mail.isLoading}
      isError={mail.hasError}
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
  );

  // Panel 3 (Message Details) — same priority order as the original
  // single-pane layout's own ternary below: selectedEmail is checked
  // ahead of selectedSystemNotification so opening a specific message
  // (e.g. via the interaction_id query param a First Response SLA
  // notification's "View Mail" link sets) always shows that message,
  // and an OTP-forward row opened from the regular Inbox tab (see
  // otpNotificationToInboxItem/openThread in useMailInbox.ts, which
  // sets selectedSystemNotification without touching activeView) shows
  // its notification detail here while Panel 2 keeps showing whatever
  // list was already active — genuinely better Outlook-style behavior
  // than the single-pane layout could offer, since the list never has
  // to be replaced just to show that one notification.
  const desktopDetailPanel = composeOpen ? (
    <ComposeView
      variant="panel"
      clients={mail.clients}
      clientsLoading={mail.clientsLoading}
      clientsError={mail.clientsError}
      initialValues={composeInitialValues}
      isSending={mail.isComposing || mail.isForwarding}
      onSend={handleComposeSend}
      onForwardSend={handleForwardSend}
      onDiscard={closeCompose}
      onBack={handleComposeBack}
    />
  ) : selectedEmail ? (
    <MessageDetailsView
      variant="panel"
      email={selectedEmail}
      folders={mail.folders}
      onBack={() => setSelectedEmail(null)}
      onRefreshList={mail.refresh}
      onRefreshMessage={handleRefreshMessage}
      isRefreshingMessage={mail.openingId === selectedEmail.interaction_id}
      onForward={handleForward}
      onSaveDraft={mail.saveDraftMessage}
      onSendDraft={mail.sendDraftMessage}
      onDiscardDraft={mail.discardDraftMessage}
      onUploadDraftAttachment={mail.uploadDraftAttachment}
      onRemoveDraftAttachment={mail.removeDraftAttachment}
      onUpdateTags={mail.updateTags}
      onAssignFolder={mail.assignFolder}
      onMarkRead={mail.markRead}
      onMarkUnread={mail.markUnread}
    />
  ) : mail.selectedSystemNotification ? (
    <SystemMailDetailsView
      variant="panel"
      notification={mail.selectedSystemNotification}
      onBack={mail.clearSelectedSystemNotification}
      onMarkRead={mail.markSystemNotificationRead}
    />
  ) : (
    <MailReadingPaneEmptyState />
  );

  return (
    <AppLayout>
      {/* No title passed above (per Mail spec: no page header) — the
          top navbar (h-16) + main's own p-6 padding are the only other
          chrome. Desktop scrolling model: MailWorkspaceLayout's outer
          container owns the one fixed, viewport-relative height
          (calc(100vh-7rem), matching that chrome); each of its three
          panels scrolls independently within it (the folder panel and
          message list via their own existing internal scroll regions,
          the reading pane via the generic wrapper MailWorkspaceLayout
          gives it) — `main`'s own overflow-y-auto never becomes the
          scroll container here. Below `lg`, the fallback pane keeps the
          pre-redesign behavior: MailSidebar/MessageList each own that
          same fixed height with their own internal scrollbar, while
          MessageDetailsView/ComposeView are left auto-height so a long
          thread or a tall reply composer just grows the page instead of
          being clipped, scrolled via `main`'s own overflow-y-auto. */}
      {isDesktop ? (
        rulesOpen ? (
          <MailWorkspaceLayout folderPanel={renderSidebar("panel")} wideContent={<RulesPanel onFoldersMayHaveChanged={mail.refreshFolders} />} />
        ) : (
          <MailWorkspaceLayout
            folderPanel={renderSidebar("panel")}
            listPanel={desktopListPanel}
            detailPanel={desktopDetailPanel}
          />
        )
      ) : (
        <div className="flex flex-col gap-4">
          {renderSidebar("standalone")}

          <div className="min-h-[560px] min-w-0 flex-1">
            {rulesOpen ? (
              <RulesPanel onFoldersMayHaveChanged={mail.refreshFolders} />
            ) : composeOpen ? (
              <ComposeView
                clients={mail.clients}
                clientsLoading={mail.clientsLoading}
                clientsError={mail.clientsError}
                initialValues={composeInitialValues}
                isSending={mail.isComposing || mail.isForwarding}
                onSend={handleComposeSend}
                onForwardSend={handleForwardSend}
                onDiscard={closeCompose}
                onBack={handleComposeBack}
              />
            ) : selectedEmail ? (
              // Checked ahead of the System-folder branch below: opening a
              // specific message (e.g. via the interaction_id query param a
              // First Response SLA notification's "View Mail" link sets,
              // handled by the effect above) must show that message even
              // while activeView is still "system" from wherever the click
              // originated — otherwise this branch never runs, since
              // activeView doesn't change on its own and the System view
              // would keep rendering in front of it.
              <MessageDetailsView
                email={selectedEmail}
                folders={mail.folders}
                onBack={() => setSelectedEmail(null)}
                onRefreshList={mail.refresh}
                onRefreshMessage={handleRefreshMessage}
                isRefreshingMessage={mail.openingId === selectedEmail.interaction_id}
                onForward={handleForward}
                onSaveDraft={mail.saveDraftMessage}
                onSendDraft={mail.sendDraftMessage}
                onDiscardDraft={mail.discardDraftMessage}
                onUploadDraftAttachment={mail.uploadDraftAttachment}
                onRemoveDraftAttachment={mail.removeDraftAttachment}
                onUpdateTags={mail.updateTags}
                onAssignFolder={mail.assignFolder}
                onMarkRead={mail.markRead}
                onMarkUnread={mail.markUnread}
              />
            ) : mail.activeFolderId ? (
              <MessageList
                folderLabel={`${mail.folders.find((f) => f.folder_id === mail.activeFolderId)?.name.trim() ?? "Folder"} (${mail.folderRowsTotal})`}
                items={mail.folderRows}
                isLoading={mail.isFolderLoading}
                isError={mail.hasFolderError}
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
                hasMore={mail.folderRowsHasMore}
                onLoadMore={mail.loadMoreFolderRows}
              />
            ) : mail.activeView === "system" || mail.selectedSystemNotification ? (
              // The `||` half covers an OTP-forward row opened from the
              // regular Inbox tab (see otpNotificationToInboxItem/
              // openThread in useMailInbox.ts) — activeView stays
              // "pending" there, so this branch must not be gated on
              // activeView alone the way it used to be.
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
                  isError={mail.hasError}
                  onOpen={mail.selectSystemNotification}
                  onRefresh={mail.refresh}
                />
              )
            ) : (
              <MessageList
                folderLabel={folderLabel}
                items={mail.filteredItems}
                isLoading={mail.isLoading}
                isError={mail.hasError}
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
      )}
    </AppLayout>
  );
}
