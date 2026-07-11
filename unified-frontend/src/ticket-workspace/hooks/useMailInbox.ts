import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import {
  composeEmail as composeEmailRequest,
  discardDraft,
  getDrafts,
  getFolderCounts,
  getInbox,
  getSent,
  getViewCounts,
  openInboxThread,
  saveDraft,
  sendDraft,
  updateInteractionFolder,
  updateInteractionTags,
  uploadDraftAttachment as uploadDraftAttachmentRequest,
  type ComposeEmailPayload,
} from "@tw/api/inbox";
import { deleteAttachment } from "@tw/api/interaction";
import { createMailFolder, deleteMailFolder, listMailFolders } from "@tw/api/mailFolder";
import { listClients } from "@tw/api/clients";
import { listCategories } from "@tw/api/categories";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type {
  CategoryResponse,
  ClientResponse,
  DraftItem,
  InboxItem,
  InboxView,
  MailFolder,
  SentItem,
} from "@tw/types";

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
    interaction_id: item.interaction_id,
    open_interaction_id: item.root_interaction_id ?? item.interaction_id,
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
    ticket_priority: null,
    ticket_category: null,
    has_attachments: false,
    claimed_by: null,
    claimed_by_name: null,
    tags: [],
    folder_id: null,
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
    interaction_id: item.interaction_id,
    open_interaction_id: item.root_interaction_id ?? item.interaction_id,
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
    ticket_priority: null,
    ticket_category: null,
    has_attachments: false,
    claimed_by: null,
    claimed_by_name: null,
    tags: [],
    folder_id: null,
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

// Sender, Receiver, Subject, and Message Body/preview — matches the
// Mail spec's search requirement (search must span all four).
const SEARCHABLE_FIELDS: Array<(item: InboxItem) => string> = [
  (item) => item.client_name,
  (item) => item.subject,
  (item) => item.from_email ?? "",
  (item) => item.to_email ?? "",
  (item) => item.latest_message ?? "",
];

function matchesSearch(item: InboxItem, term: string): boolean {
  if (!term) return true;
  return SEARCHABLE_FIELDS.some((getField) => getField(item).toLowerCase().includes(term));
}

type BaseTabKey = "pending" | "replied" | "ticketed" | "archived" | "all";
type LoadKey = BaseTabKey | "sent" | "drafts";

// Maps a view the agent is looking at to the underlying fetch(es) it
// actually needs — "unassigned"/"mine" are client-derived slices of
// "pending"(/"replied"), not separate backend views, so opening them
// only ever needs to load their source tab(s), never a request of
// their own.
function baseKeysForView(view: MailViewKey): LoadKey[] {
  switch (view) {
    case "unassigned":
      return ["pending"];
    case "mine":
      return ["pending", "replied"];
    default:
      return [view];
  }
}

/**
 * Owns all Mail-page state: fetching every base view in parallel,
 * deriving the "unassigned"/"mine" client-side views from "pending",
 * search/client/time filtering, custom-folder browsing (orthogonal to
 * `activeView` — composes as `view=all&folder_id=X`), and the
 * open-thread/tag/folder actions. Extracted from what used to
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
    all: [],
  });
  const [sentItems, setSentItems] = useState<InboxItem[]>([]);
  const [draftItems, setDraftItems] = useState<InboxItem[]>([]);
  // Real Pending/Replied/Ticketed/Archived/All counts, fetched
  // eagerly via one cheap aggregate query — kept separate from
  // rowsByTab so the sidebar badges stay accurate even for a tab
  // whose actual row data hasn't been fetched yet (see loadedKeysRef
  // below).
  const [baseViewCounts, setBaseViewCounts] = useState<Record<BaseTabKey, number>>({
    pending: 0,
    replied: 0,
    ticketed: 0,
    archived: 0,
    all: 0,
  });
  // Which views/tabs have actually been fetched at least once — a
  // ref, not state, since it's pure bookkeeping read by refresh()/
  // ensureLoaded() and must never itself trigger a re-render or be a
  // useCallback dependency (both of those would set up a feedback
  // loop, since refresh() is what populates it).
  const loadedKeysRef = useRef<Set<LoadKey>>(new Set());
  const prevClientFilterRef = useRef<string>("ALL");
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

  // Category "folders" (Eligibility, Claims, AR, ...) are a fixed,
  // backend-known set — not a custom mail_folders row. Sliced
  // client-side from the already-fetched "ticketed" set (same
  // no-extra-request pattern as unassigned/mine below), keyed by
  // Ticket.ticket_type via InboxItem.ticket_category.
  const [categories, setCategories] = useState<CategoryResponse[]>([]);
  const [activeCategory, setActiveCategoryRaw] = useState<string | null>(null);

  const { run: runOpen } = useApiAction(openInboxThread);
  const { run: runUpdateTags } = useApiAction(updateInteractionTags);
  const { run: runUpdateFolder } = useApiAction(updateInteractionFolder);
  const { run: runCreateFolder } = useApiAction(createMailFolder);
  const { run: runDeleteFolder } = useApiAction(deleteMailFolder);
  const { run: runSaveDraft } = useApiAction(saveDraft);
  const { run: runSendDraft } = useApiAction(sendDraft);
  const { run: runDiscardDraft } = useApiAction(discardDraft);
  const { run: runUploadDraftAttachment } = useApiAction(uploadDraftAttachmentRequest);
  const { run: runDeleteAttachment } = useApiAction(deleteAttachment);
  const { run: runCompose, isLoading: isComposing } = useApiAction(composeEmailRequest, {
    successMessage: "Email sent.",
  });

  const setActiveView = useCallback((view: MailViewKey) => {
    setActiveFolderRaw(null);
    setActiveCategoryRaw(null);
    setActiveViewRaw(view);
  }, []);

  const setActiveFolder = useCallback((folderId: string | null) => {
    setActiveCategoryRaw(null);
    setActiveFolderRaw(folderId);
  }, []);

  const setActiveCategory = useCallback((category: string | null) => {
    setActiveFolderRaw(null);
    setActiveCategoryRaw(category);
  }, []);

  // Fetches one base tab's actual row data — the thing that used to
  // happen eagerly for every tab on every load/refresh, regardless of
  // which one the agent was actually looking at.
  const fetchBaseTab = useCallback(
    async (key: BaseTabKey) => {
      if (key === "all" && !isSupervisor) {
        setRowsByTab((prev) => ({ ...prev, all: [] }));
        return;
      }
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;
      const result = await getInbox(key, { clientId, scope: key === "all" ? "all" : undefined });
      setRowsByTab((prev) => ({ ...prev, [key]: result.items }));
    },
    [clientFilter, isSupervisor]
  );

  const fetchSent = useCallback(async () => {
    const result = await getSent();
    setSentItems(result.items.map(sentItemToInboxItem));
  }, []);

  const fetchDrafts = useCallback(async () => {
    const result = await getDrafts();
    setDraftItems(result.items.map(draftItemToInboxItem));
  }, []);

  const fetchKey = useCallback(
    (key: LoadKey) => {
      if (key === "sent") return fetchSent();
      if (key === "drafts") return fetchDrafts();
      return fetchBaseTab(key);
    },
    [fetchBaseTab, fetchSent, fetchDrafts]
  );

  // Fetches only whichever of `keys` haven't been loaded yet — used
  // when the agent switches to a view/tab for the first time. Once
  // loaded, a tab's data stays cached in rowsByTab/sentItems/draftItems
  // (re-switching back to it is instant, no re-fetch) until the next
  // refresh() call actually re-pulls it.
  const ensureLoaded = useCallback(
    async (keys: LoadKey[]) => {
      const missing = keys.filter((key) => !loadedKeysRef.current.has(key));
      if (missing.length === 0) return;
      missing.forEach((key) => loadedKeysRef.current.add(key));
      await Promise.all(missing.map((key) => fetchKey(key)));
    },
    [fetchKey]
  );

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;

      // A client-filter change invalidates every previously-loaded
      // tab's cached data (it was scoped to the old filter) — start
      // this refresh as if nothing had been fetched yet, same as the
      // very first load.
      if (prevClientFilterRef.current !== clientFilter) {
        loadedKeysRef.current = new Set();
        prevClientFilterRef.current = clientFilter;
      }

      // Sidebar chrome (client list, folders, categories) plus real
      // Pending/Replied/Ticketed/Archived/All counts and per-folder
      // counts — both via one cheap aggregate query each, regardless
      // of which tabs have actually been opened — stay eager so the
      // sidebar never shows a misleadingly-zero badge.
      const [clientList, folderList, categoryList, viewCounts, folderCountsResult] =
        await Promise.all([
          listClients(),
          listMailFolders(),
          listCategories(),
          getViewCounts(clientId),
          getFolderCounts(clientId),
        ]);

      setClients(clientList);
      setFolders(folderList);
      // Team Lead/Staff are already category-scoped to their own
      // single category everywhere else (ensure_agent_can_view_ticket) —
      // a category filter is redundant (and would just show one
      // enabled entry) for them. Only roles that see across multiple
      // categories (Account Manager, Site Lead, Super Admin) get it.
      const isCategoryScopedRole = currentUser?.role === "Team Lead" || currentUser?.role === "Staff";
      setCategories(isCategoryScopedRole ? [] : categoryList);
      setBaseViewCounts(viewCounts);
      setFolderCounts(folderCountsResult);

      // Re-fetch every tab already visited (so previously-seen data
      // stays fresh after a mutation), plus whichever tab is active
      // right now (covers the very first load, before anything's
      // been marked loaded).
      const keysToRefresh = new Set(loadedKeysRef.current);
      baseKeysForView(activeViewRaw).forEach((key) => keysToRefresh.add(key));
      keysToRefresh.forEach((key) => loadedKeysRef.current.add(key));
      await Promise.all(Array.from(keysToRefresh).map((key) => fetchKey(key)));
    } catch (error) {
      pushToast(
        error instanceof Error ? error.message : "Failed to load inbox.",
        "error"
      );
    } finally {
      setIsLoading(false);
    }
  }, [pushToast, clientFilter, activeViewRaw, fetchKey, currentUser]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientFilter]);

  // Lazy-load a view/tab's data the first time the agent actually
  // switches to it.
  useEffect(() => {
    ensureLoaded(baseKeysForView(activeViewRaw));
  }, [activeViewRaw, ensureLoaded]);

  // Category filtering slices the already-fetched "ticketed" set —
  // make sure that data actually exists once a category is selected.
  useEffect(() => {
    if (activeCategory) {
      ensureLoaded(["ticketed"]);
    }
  }, [activeCategory, ensureLoaded]);

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

  async function saveDraftMessage(
    interactionId: string,
    message: string,
    cc: string[] = [],
    bcc: string[] = []
  ) {
    const result = await runSaveDraft(interactionId, message, cc, bcc);
    if (result && selectedEmail?.interaction_id === interactionId) {
      setSelectedEmail({
        ...selectedEmail,
        draft_message: result.message,
        draft_cc: result.cc,
        draft_bcc: result.bcc,
        draft_attachments: result.attachments,
      });
    }
    return result;
  }

  // Re-fetches the full thread (rather than hand-building the new
  // reply locally) so the sent reply's attachments — reassigned
  // server-side from the now-deleted draft onto it — actually show
  // up immediately, instead of only after the thread is reopened.
  async function sendDraftMessage(interactionId: string, toEmail?: string | null) {
    const result = await runSendDraft(interactionId, toEmail);
    if (result && selectedEmail?.interaction_id === interactionId) {
      const fresh = await openInboxThread(interactionId);
      setSelectedEmail(fresh);
    }
    if (result) await refresh();
    return result;
  }

  async function discardDraftMessage(interactionId: string) {
    const result = await runDiscardDraft(interactionId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({
          ...selectedEmail,
          draft_message: null,
          draft_cc: [],
          draft_bcc: [],
          draft_attachments: [],
        });
      }
      await refresh();
    }
    return Boolean(result);
  }

  async function uploadDraftAttachment(interactionId: string, files: File[]) {
    const result = await runUploadDraftAttachment(interactionId, files);
    if (result && selectedEmail?.interaction_id === interactionId) {
      setSelectedEmail({
        ...selectedEmail,
        draft_attachments: [...selectedEmail.draft_attachments, ...result],
      });
    }
    return result;
  }

  async function removeDraftAttachment(interactionId: string, attachmentId: string) {
    const result = await runDeleteAttachment(attachmentId);
    if (result !== null && selectedEmail?.interaction_id === interactionId) {
      setSelectedEmail({
        ...selectedEmail,
        draft_attachments: selectedEmail.draft_attachments.filter((a) => a.id !== attachmentId),
      });
    }
    return result !== null;
  }

  async function composeEmail(payload: ComposeEmailPayload) {
    const result = await runCompose(payload);
    if (result) {
      await refresh();
    }
    return result;
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
  // De-duped by interaction_id: `pending` and `replied` are two
  // independently-fetched arrays (parallel requests in refresh()), so
  // an item whose status flips between those two fetches could
  // otherwise land in both and duplicate here.
  const mine = Array.from(
    new Map(
      [...rowsByTab.pending, ...rowsByTab.replied]
        .filter((item) => item.claimed_by === currentUser?.user_id)
        .map((item) => [item.interaction_id, item])
    ).values()
  );

  // Category counts/items, derived from the already-fetched "ticketed"
  // set — only ticketed rows carry a real ticket_category, so this
  // is naturally a slice of Ticketed, not a separate mail state.
  const categoryCounts: Record<string, number> = {};
  for (const item of rowsByTab.ticketed) {
    if (item.ticket_category) {
      categoryCounts[item.ticket_category] = (categoryCounts[item.ticket_category] ?? 0) + 1;
    }
  }
  const categoryItems = activeCategory
    ? rowsByTab.ticketed.filter((item) => item.ticket_category === activeCategory)
    : [];

  const rowsByView: Record<MailViewKey, InboxItem[]> = {
    pending: rowsByTab.pending,
    replied: rowsByTab.replied,
    ticketed: rowsByTab.ticketed,
    archived: rowsByTab.archived,
    all: rowsByTab.all,
    unassigned,
    mine,
    sent: sentItems,
    drafts: draftItems,
  };

  // Pending/Replied/Ticketed/Archived/All come from the eager
  // aggregate query (accurate even before that tab's row data has
  // been fetched); Unassigned/Mine/Sent/Drafts are narrower derived
  // views with no aggregate of their own, so their badge counts
  // reflect whatever's actually been loaded so far.
  const viewCounts: Record<MailViewKey, number> = {
    ...baseViewCounts,
    unassigned: unassigned.length,
    mine: mine.length,
    sent: sentItems.length,
    drafts: draftItems.length,
  };

  const filteredItems = activeCategory
    ? applyFilters(categoryItems)
    : activeFolder
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
    categories,
    categoryCounts,
    activeCategory,
    setActiveCategory,
    updateTags,
    assignFolder,
    saveDraftMessage,
    sendDraftMessage,
    discardDraftMessage,
    uploadDraftAttachment,
    removeDraftAttachment,
    composeEmail,
    isComposing,
  };
}
