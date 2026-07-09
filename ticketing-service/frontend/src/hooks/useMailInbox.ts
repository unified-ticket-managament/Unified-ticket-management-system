import { useCallback, useEffect, useMemo, useState } from "react";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import {
  discardDraft,
  getDrafts,
  getInbox,
  getSent,
  openInboxThread,
  saveDraft,
  sendDraft,
  snoozeInteraction,
  unsnoozeInteraction,
  updateInteractionFolder,
  updateInteractionTags,
} from "@/api/inbox";
import { createMailFolder, deleteMailFolder, listMailFolders } from "@/api/mailFolder";
import { listClients } from "@/api/clients";
import { useApiAction } from "@/hooks/useApiAction";
import { useAuthContext } from "@/context/AuthContext";
import { useToast } from "@/context/ToastContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { ClientResponse, DraftItem, InboxItem, InboxResponse, InboxView, MailFolder, SentItem } from "@/types";

const SUPERVISOR_ROLES = ["Site Lead", "Super Admin"];

// "Unassigned"/"My Claims" aren't separate backend views — they're
// derived client-side from the "pending" set (claimed_by null vs.
// mine), same data, no extra network round-trip. "sent"/"drafts" are
// their own endpoints (GET /inbox/sent, GET /inbox/drafts), not one
// of the backend's `view` values.
export type MailViewKey = InboxView | "unassigned" | "mine" | "sent" | "drafts";

// A sent reply carries no subject/client_name/status of its own (see
// SentItemResponse) — adapted into InboxItem shape so the existing
// message-list UI can render it without a parallel row component.
// Clicking it opens the *thread root*, not the reply itself: GET
// /inbox/{id} builds its response from EmailPayload, which a bare
// REPLY interaction's payload doesn't match.
function sentItemToInboxItem(item: SentItem): InboxItem {
  return {
    interaction_id: item.root_interaction_id ?? item.interaction_id,
    client_id: item.client_id,
    client_name: item.client_name,
    from_email: null,
    to_email: null,
    subject: item.subject,
    message_id: null,
    received_at: item.sent_at,
    status: "ASSIGNED",
    direction: "OUTBOUND",
    ticket_id: item.ticket_id,
    has_attachments: false,
    claimed_by: null,
    claimed_by_name: null,
    tags: [],
    folder_id: null,
    snoozed_until: null,
    reply_count: 0,
    latest_message: null,
    latest_sender: null,
    latest_at: null,
  };
}

// Same reasoning as sentItemToInboxItem — a draft carries no
// subject/client_name of its own, and clicking it should open the
// thread root, not the draft row itself.
function draftItemToInboxItem(item: DraftItem): InboxItem {
  return {
    interaction_id: item.root_interaction_id ?? item.interaction_id,
    client_id: item.client_id,
    client_name: item.client_name,
    from_email: null,
    to_email: null,
    subject: item.subject,
    message_id: null,
    received_at: item.created_at,
    status: "PENDING",
    direction: "OUTBOUND",
    ticket_id: null,
    has_attachments: false,
    claimed_by: null,
    claimed_by_name: null,
    tags: [],
    folder_id: null,
    snoozed_until: null,
    reply_count: 0,
    latest_message: null,
    latest_sender: null,
    latest_at: null,
  };
}

export type TimeFilterKey = "ALL" | "1H" | "TODAY" | "24H" | "1W";

export const TIME_FILTERS: Array<{ key: TimeFilterKey; label: string }> = [
  { key: "ALL", label: "All Time" },
  { key: "1H", label: "Last 1 Hour" },
  { key: "TODAY", label: "Today" },
  { key: "24H", label: "Last 24 Hours" },
  { key: "1W", label: "Last 1 Week" },
];

function isWithinTimeFilter(receivedAt: string, filter: TimeFilterKey, now: Date): boolean {
  if (filter === "ALL") return true;

  const receivedTime = new Date(receivedAt).getTime();
  const nowTime = now.getTime();

  switch (filter) {
    case "1H":
      return nowTime - receivedTime <= 60 * 60 * 1000;
    case "24H":
      return nowTime - receivedTime <= 24 * 60 * 60 * 1000;
    case "1W":
      return nowTime - receivedTime <= 7 * 24 * 60 * 60 * 1000;
    case "TODAY": {
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      return receivedTime >= startOfToday;
    }
    default:
      return true;
  }
}

const SEARCHABLE_FIELDS: Array<(item: InboxItem) => string> = [
  (item) => item.client_name,
  (item) => item.subject,
  (item) => item.from_email ?? "",
];

function matchesSearch(item: InboxItem, term: string): boolean {
  if (!term) return true;
  return SEARCHABLE_FIELDS.some((getField) => getField(item).toLowerCase().includes(term));
}

type BaseTabKey = "pending" | "replied" | "ticketed" | "archived" | "snoozed" | "all";

/**
 * Owns all Mail-page state: fetching every base view in parallel,
 * deriving the "unassigned"/"mine" client-side views from "pending",
 * search/client/time filtering, custom-folder browsing (orthogonal to
 * `activeView` — composes as `view=all&folder_id=X`), and the
 * open-thread/snooze/tag/folder actions. Extracted from what used to
 * be AgentInbox.tsx's internal state so the new MailSidebar
 * (counts/view switching) and the message list can share one source
 * of truth without prop-drilling through a rewritten AgentInbox.
 */
export function useMailInbox() {
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();

  const isSupervisor = Boolean(currentUser && SUPERVISOR_ROLES.includes(currentUser.role));

  const [rowsByTab, setRowsByTab] = useState<Record<BaseTabKey, InboxItem[]>>({
    pending: [],
    replied: [],
    ticketed: [],
    archived: [],
    snoozed: [],
    all: [],
  });
  const [sentItems, setSentItems] = useState<InboxItem[]>([]);
  const [draftItems, setDraftItems] = useState<InboxItem[]>([]);
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeViewRaw, setActiveViewRaw] = useState<MailViewKey>("pending");
  const [clientFilter, setClientFilter] = useState<string>("ALL");
  const [timeFilter, setTimeFilter] = useState<TimeFilterKey>("ALL");
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());

  const [folders, setFolders] = useState<MailFolder[]>([]);
  const [folderCounts, setFolderCounts] = useState<Record<string, number>>({});
  const [activeFolder, setActiveFolderRaw] = useState<string | null>(null);
  const [folderItems, setFolderItems] = useState<InboxItem[]>([]);
  const [isFolderLoading, setIsFolderLoading] = useState(false);

  const { run: runOpen } = useApiAction(openInboxThread);
  const { run: runSnooze } = useApiAction(snoozeInteraction);
  const { run: runUnsnooze } = useApiAction(unsnoozeInteraction);
  const { run: runUpdateTags } = useApiAction(updateInteractionTags);
  const { run: runUpdateFolder } = useApiAction(updateInteractionFolder);
  const { run: runCreateFolder } = useApiAction(createMailFolder);
  const { run: runDeleteFolder } = useApiAction(deleteMailFolder);
  const { run: runSaveDraft } = useApiAction(saveDraft);
  const { run: runSendDraft } = useApiAction(sendDraft);
  const { run: runDiscardDraft } = useApiAction(discardDraft);

  const setActiveView = useCallback((view: MailViewKey) => {
    setActiveFolderRaw(null);
    setActiveViewRaw(view);
  }, []);

  const setActiveFolder = useCallback((folderId: string | null) => {
    setActiveFolderRaw(folderId);
  }, []);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;
      const scope = isSupervisor ? "all" : undefined;

      // The supervisor-only "all" view used to be a second sequential
      // stage after this batch resolved — folded in here (as a no-op
      // resolved promise for non-supervisors) so every base view is
      // one single round-trip stage regardless of role.
      const [pending, replied, ticketed, archived, snoozed, sent, drafts, clientList, folderList, all] =
        await Promise.all([
          getInbox("pending", { clientId }),
          getInbox("replied", { clientId }),
          getInbox("ticketed", { clientId }),
          getInbox("archived", { clientId }),
          getInbox("snoozed", { clientId }),
          getSent(),
          getDrafts(),
          listClients(),
          listMailFolders(),
          isSupervisor
            ? getInbox("all", { clientId, scope: "all" })
            : Promise.resolve<InboxResponse>({ total: 0, items: [] }),
        ]);

      setSentItems(sent.items.map(sentItemToInboxItem));
      setDraftItems(drafts.items.map(draftItemToInboxItem));

      const next: Record<BaseTabKey, InboxItem[]> = {
        pending: pending.items,
        replied: replied.items,
        ticketed: ticketed.items,
        archived: archived.items,
        snoozed: snoozed.items,
        all: isSupervisor ? all.items : [],
      };

      setRowsByTab(next);
      setClients(clientList);
      setFolders(folderList);

      const counts = await Promise.all(
        folderList.map((folder) => getInbox("all", { clientId, scope, folderId: folder.folder_id }))
      );
      setFolderCounts(
        Object.fromEntries(folderList.map((folder, index) => [folder.folder_id, counts[index].total]))
      );
    } catch (error) {
      pushToast(
        error instanceof Error ? error.message : "Failed to load inbox.",
        "error"
      );
    } finally {
      setIsLoading(false);
    }
  }, [pushToast, clientFilter, isSupervisor]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!activeFolder) {
      setFolderItems([]);
      return;
    }

    let cancelled = false;
    setIsFolderLoading(true);
    const clientId = clientFilter === "ALL" ? undefined : clientFilter;

    getInbox("all", { clientId, scope: isSupervisor ? "all" : undefined, folderId: activeFolder })
      .then((result) => {
        if (!cancelled) setFolderItems(result.items);
      })
      .catch((error) => {
        if (!cancelled) {
          pushToast(error instanceof Error ? error.message : "Failed to load folder.", "error");
        }
      })
      .finally(() => {
        if (!cancelled) setIsFolderLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeFolder, clientFilter, isSupervisor, pushToast]);

  async function openThread(interactionId: string) {
    setOpeningId(interactionId);
    const result = await runOpen(interactionId);
    setOpeningId(null);

    if (result) {
      setSelectedEmail(result);
      setOpenedIds((prev) => {
        const next = new Set(prev);
        next.add(interactionId);
        return next;
      });
    }
  }

  async function snoozeItem(interactionId: string, snoozeUntil: string) {
    const result = await runSnooze(interactionId, snoozeUntil);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, snoozed_until: result.snoozed_until });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function unsnoozeItem(interactionId: string) {
    const result = await runUnsnooze(interactionId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, snoozed_until: result.snoozed_until });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function updateTags(interactionId: string, tags: string[]) {
    const result = await runUpdateTags(interactionId, tags);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, tags: result.tags });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function assignFolder(interactionId: string, folderId: string | null) {
    const result = await runUpdateFolder(interactionId, folderId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, folder_id: result.folder_id });
      }
      await refresh();
      if (activeFolder) {
        setFolderItems((prev) => prev.filter((item) => item.interaction_id !== interactionId));
      }
    }
    return Boolean(result);
  }

  async function saveDraftMessage(interactionId: string, message: string) {
    const result = await runSaveDraft(interactionId, message);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, draft_message: result.message });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function sendDraftMessage(interactionId: string) {
    const result = await runSendDraft(interactionId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({
          ...selectedEmail,
          status: "ASSIGNED",
          draft_message: null,
          replies: [
            ...selectedEmail.replies,
            {
              interaction_id: result.interaction_id,
              ticket_id: null,
              interaction_type: "REPLY",
              status: "ASSIGNED",
              direction: "OUTBOUND",
              performed_by: null,
              payload: { message: result.message },
              is_visible: true,
              removed_by: null,
              removed_at: null,
              message_id: null,
              parent_interaction_id: result.parent_interaction_id,
              created_at: result.created_at,
            },
          ],
        });
      }
      await refresh();
    }
    return result;
  }

  async function discardDraftMessage(interactionId: string) {
    const result = await runDiscardDraft(interactionId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, draft_message: null });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function createFolder(name: string) {
    const folder = await runCreateFolder(name);
    if (folder) {
      setFolders((prev) => [...prev, folder].sort((a, b) => a.name.localeCompare(b.name)));
      setFolderCounts((prev) => ({ ...prev, [folder.folder_id]: 0 }));
    }
    return folder;
  }

  async function deleteFolder(folderId: string) {
    const result = await runDeleteFolder(folderId);
    if (result !== null) {
      setFolders((prev) => prev.filter((folder) => folder.folder_id !== folderId));
      setFolderCounts((prev) => {
        const next = { ...prev };
        delete next[folderId];
        return next;
      });
      if (activeFolder === folderId) {
        setActiveFolderRaw(null);
      }
    }
  }

  const now = useMemo(() => new Date(), [rowsByTab, sentItems, draftItems, timeFilter]);
  const debouncedSearch = useDebouncedValue(search, 300);
  const term = debouncedSearch.trim().toLowerCase();

  const applyFilters = useCallback(
    (rows: InboxItem[]) =>
      rows.filter(
        (row) => isWithinTimeFilter(row.received_at, timeFilter, now) && matchesSearch(row, term)
      ),
    [timeFilter, now, term]
  );

  const unassigned = rowsByTab.pending.filter((item) => !item.claimed_by);
  const mine = [...rowsByTab.pending, ...rowsByTab.replied].filter(
    (item) => item.claimed_by === currentUser?.user_id
  );

  const rowsByView: Record<MailViewKey, InboxItem[]> = {
    pending: rowsByTab.pending,
    replied: rowsByTab.replied,
    ticketed: rowsByTab.ticketed,
    archived: rowsByTab.archived,
    snoozed: rowsByTab.snoozed,
    all: rowsByTab.all,
    unassigned,
    mine,
    sent: sentItems,
    drafts: draftItems,
  };

  const viewCounts: Record<MailViewKey, number> = Object.fromEntries(
    Object.entries(rowsByView).map(([key, rows]) => [key, rows.length])
  ) as Record<MailViewKey, number>;

  const filteredItems = activeFolder
    ? applyFilters(folderItems)
    : applyFilters(rowsByView[activeViewRaw]);

  const managedClientCount = currentUser
    ? clients.filter((c) => c.account_manager_id === currentUser.user_id).length
    : 0;

  return {
    isSupervisor,
    isLoading: activeFolder ? isFolderLoading : isLoading,
    openingId,
    openedIds,
    clients,
    clientFilter,
    setClientFilter,
    timeFilter,
    setTimeFilter,
    search,
    setSearch,
    activeView: activeViewRaw,
    setActiveView,
    viewCounts,
    filteredItems,
    managedClientCount,
    refresh,
    openThread,
    selectedEmail,
    folders,
    folderCounts,
    activeFolder,
    setActiveFolder,
    createFolder,
    deleteFolder,
    snoozeItem,
    unsnoozeItem,
    updateTags,
    assignFolder,
    saveDraftMessage,
    sendDraftMessage,
    discardDraftMessage,
  };
}
