import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import {
  composeEmail as composeEmailRequest,
  discardDraft,
  getDrafts,
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
import { listMailFolders } from "@tw/api/mailFolder";
import { getNotifications, markNotificationRead } from "@tw/api/notifications";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type {
  DraftItem,
  InboxItem,
  InboxView,
  MailFolder,
  NotificationItem,
  SentItem,
} from "@tw/types";

// Every notification_type the "System" folder shows — internal,
// system-generated notices (SLA breach ladder + the escalation
// ownership workflow), deliberately excluding MAIL_RECEIVED/
// CLIENT_REPLY (those are real client mail, already shown in the
// regular Inbox) and the unrelated PERMISSION_*/EDIT_ACCESS_*/
// TICKET_ASSIGNED types (a different notification concern, still only
// surfaced via the topbar bell for now).
export const SYSTEM_NOTIFICATION_TYPES = [
  "SLA_HALF_ELAPSED",
  "SLA_AT_RISK",
  "SLA_BREACHED",
  "SLA_ESCALATED",
  "ESCALATION_CREATED",
  "ESCALATION_ACKNOWLEDGED",
  "ESCALATION_ADVANCED",
  "ESCALATION_CLOSED",
];

const SUPERVISOR_ROLES = ["Site Lead", "Super Admin"];

// How many rows a base tab fetches at a time. GET /inbox used to be
// called with no limit at all — every matching row for a view (e.g.
// Site Lead/Super Admin's "All Inboxes") was fetched, fully enriched,
// and serialized on every load, even though MessageList only ever
// shows 10 at a time. Bounding the fetch itself (rather than just
// paginating client-side over an already-fully-loaded array) is what
// actually caps the request cost; `loadMoreBaseTab` below fetches the
// next batch on demand instead of ever pulling a tab's entire history
// up front.
const MAIL_TAB_FETCH_SIZE = 200;

// "Unassigned"/"My Claims" aren't separate backend views — they're
// derived client-side from the "pending" set (claimed_by null vs.
// mine), same data, no extra network round-trip. "sent"/"drafts" are
// their own endpoints (GET /inbox/sent, GET /inbox/drafts), not one
// of the backend's `view` values. "system" is a third such sibling —
// GET /notifications, not GET /inbox at all — see fetchSystemMail.
export type MailViewKey = InboxView | "unassigned" | "mine" | "sent" | "drafts" | "system";

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
type LoadKey = BaseTabKey | "sent" | "drafts" | "system" | "mineTicketed";

// Maps a view the agent is looking at to the underlying fetch(es) it
// actually needs — "unassigned"/"mine" are client-derived slices of
// "pending"(/"replied"), not separate backend views, so opening them
// only ever needs to load their source tab(s), never a request of
// their own. "mine" additionally needs its own dedicated
// assigned-to-me ticketed fetch ("mineTicketed") — it can't reuse the
// plain "ticketed" tab's cache, since that one is unfiltered (backs
// the separate "Ticketed" folder showing every ticketed thread in
// scope, not just this user's own).
function baseKeysForView(view: MailViewKey): LoadKey[] {
  switch (view) {
    case "unassigned":
      return ["pending"];
    case "mine":
      return ["pending", "replied", "mineTicketed"];
    default:
      return [view];
  }
}

/**
 * Owns all Mail-page state: fetching every base view in parallel,
 * deriving the "unassigned"/"mine" client-side views from "pending",
 * search/client/time filtering, and the open-thread/tag/folder
 * actions. Extracted from what used to be AgentInbox.tsx's internal
 * state so the new MailSidebar (counts/view switching) and the
 * message list can share one source of truth without prop-drilling
 * through a rewritten AgentInbox.
 */
export function useMailInbox() {
  const {
    selectedEmail,
    setSelectedEmail,
    clients,
    categories: contextCategories,
  } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();

  const isSupervisor = Boolean(currentUser && SUPERVISOR_ROLES.includes(currentUser.role));

  // Guards openThread against a fast message-to-message selection
  // change: without this, an older thread's response resolving after
  // a newer one is already selected could overwrite `selectedEmail`
  // with the wrong conversation.
  const openThreadRequestIdRef = useRef(0);

  const [rowsByTab, setRowsByTab] = useState<Record<BaseTabKey, InboxItem[]>>({
    pending: [],
    replied: [],
    ticketed: [],
    archived: [],
    all: [],
  });
  const [sentItems, setSentItems] = useState<InboxItem[]>([]);
  // Ticketed threads assigned to the current user — the "My Claims"
  // folder's post-ticket half (see fetchMyTicketedClaims below).
  const [myTicketedClaims, setMyTicketedClaims] = useState<InboxItem[]>([]);
  const [draftItems, setDraftItems] = useState<InboxItem[]>([]);
  // System notices (SLA breach ladder + escalation workflow) — real
  // NotificationItem rows, not adapted into InboxItem shape like
  // sent/draft rows are: forcing a notification through InboxItem's
  // ticket-mail vocabulary (status/priority/attachments) would either
  // need meaningless placeholder values or produce a misleading badge
  // (e.g. "Replied"/"Archived" on a system notice), so this folder
  // gets its own dedicated list/detail components instead of reusing
  // MessageList/MessageDetailsView — see SystemMailList/
  // SystemMailDetailsView.
  const [systemNotifications, setSystemNotifications] = useState<NotificationItem[]>([]);
  const [selectedSystemNotification, setSelectedSystemNotification] =
    useState<NotificationItem | null>(null);
  const [isSystemLoading, setIsSystemLoading] = useState(false);
  // The server's own filtered total per base tab (from GET /inbox's
  // `total`) — lets `hasMore` below tell "there's another batch to
  // load" apart from "this tab just happens to have exactly
  // MAIL_TAB_FETCH_SIZE rows."
  const [tabTotals, setTabTotals] = useState<Record<BaseTabKey, number>>({
    pending: 0,
    replied: 0,
    ticketed: 0,
    archived: 0,
    all: 0,
  });
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
  // One AbortController per base tab — a fast clientFilter/priority/
  // category change (or refresh()/ensureLoaded() overlapping) used to
  // leave the older, now-superseded request in flight with nothing
  // to stop it from still landing and overwriting rowsByTab with
  // stale data if it happened to resolve after the newer one. Keyed
  // per-tab (not one shared controller) so aborting "pending"'s stale
  // request never cancels an unrelated in-flight "all" fetch.
  const baseTabAbortRef = useRef<Partial<Record<BaseTabKey, AbortController>>>({});
  // Folders (this agent's own custom mail folders) are loaded once
  // and never re-fetched on a clientFilter change or later refresh()
  // call — see refresh()'s own comment for why re-fetching every time
  // was always redundant. Clients/categories no longer fetched here
  // at all — both are now shared, session-wide lookup data owned by
  // WorkflowContext (fetched once for the whole app, not once per
  // consumer — see that context's own comment).
  const chromeLoadedRef = useRef(false);
  const [isLoading, setIsLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeViewRaw, setActiveViewRaw] = useState<MailViewKey>("pending");
  const [clientFilter, setClientFilter] = useState<string>("ALL");
  // The Filters dropdown's Priority/Category selections (MessageList)
  // used to filter `items` client-side after the fact — correct only
  // as long as every matching row happened to already be in the
  // currently-loaded batch. Both are now passed to GET /inbox itself
  // (both already exist as real, indexed backend filters), same
  // invalidation treatment as clientFilter below.
  const [priorityFilter, setPriorityFilter] = useState<string>("ALL");
  const [messageCategoryFilter, setMessageCategoryFilter] = useState<string>("ALL");
  const [timeFilter, setTimeFilter] = useState<TimeFilterKey>("ALL");
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());

  // Custom mail folders — no longer browsable/manageable from the Mail
  // sidebar (that section was removed), but the list itself is still
  // needed to populate MessageDetailsView's per-email "assign to
  // folder" control, and any email already filed into one keeps that
  // filing.
  const [folders, setFolders] = useState<MailFolder[]>([]);

  // Category "folders" (Eligibility, Claims, AR, ...) are a fixed,
  // backend-known set — not a custom mail_folders row, and (as of
  // this session) not fetched here at all: WorkflowContext already
  // fetches the full category list once for the whole app, so this
  // just applies the same role-based visibility filter to it that
  // used to be applied at fetch time.
  // Team Lead/Staff are already category-scoped to their own single
  // category everywhere else (ensure_agent_can_view_ticket) — a
  // category filter is redundant (and would just show one enabled
  // entry) for them. Only roles that see across multiple categories
  // (Account Manager, Site Lead, Super Admin) get it.
  const isCategoryScopedRole = currentUser?.role === "Team Lead" || currentUser?.role === "Staff";
  const categories = useMemo(
    () => (isCategoryScopedRole ? [] : contextCategories),
    [isCategoryScopedRole, contextCategories]
  );

  const { run: runOpen } = useApiAction(openInboxThread);
  const { run: runUpdateTags } = useApiAction(updateInteractionTags);
  const { run: runUpdateFolder } = useApiAction(updateInteractionFolder);
  const { run: runSaveDraft } = useApiAction(saveDraft);
  const { run: runSendDraft } = useApiAction(sendDraft);
  const { run: runDiscardDraft } = useApiAction(discardDraft);
  const { run: runUploadDraftAttachment } = useApiAction(uploadDraftAttachmentRequest);
  const { run: runDeleteAttachment } = useApiAction(deleteAttachment);
  const { run: runCompose, isLoading: isComposing } = useApiAction(composeEmailRequest, {
    successMessage: "Email sent.",
  });

  const setActiveView = useCallback((view: MailViewKey) => {
    setActiveViewRaw(view);
    setSelectedSystemNotification(null);
  }, []);

  // Fetches one base tab's actual row data — the thing that used to
  // happen eagerly for every tab on every load/refresh, regardless of
  // which one the agent was actually looking at. Bounded to the
  // first MAIL_TAB_FETCH_SIZE rows (see loadMoreBaseTab for how a
  // tab with more than that gets the rest) instead of the tab's
  // entire history.
  const fetchBaseTab = useCallback(
    async (key: BaseTabKey) => {
      if (key === "all" && !isSupervisor) {
        setRowsByTab((prev) => ({ ...prev, all: [] }));
        setTabTotals((prev) => ({ ...prev, all: 0 }));
        return;
      }
      baseTabAbortRef.current[key]?.abort();
      const controller = new AbortController();
      baseTabAbortRef.current[key] = controller;
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;
      try {
        const result = await getInbox(
          key,
          {
            clientId,
            scope: key === "all" ? "all" : undefined,
            limit: MAIL_TAB_FETCH_SIZE,
            offset: 0,
            priority: priorityFilter === "ALL" ? undefined : priorityFilter,
            category: messageCategoryFilter === "ALL" ? undefined : messageCategoryFilter,
          },
          controller.signal
        );
        setRowsByTab((prev) => ({ ...prev, [key]: result.items }));
        setTabTotals((prev) => ({ ...prev, [key]: result.total }));
      } catch (error) {
        // axios.isCancel, not error.name/instanceof — client.ts's
        // response interceptor now passes a canceled request through
        // unchanged specifically so this check keeps working; it used
        // to rewrap every rejection into a plain Error first, which
        // erased everything about the original CanceledError except
        // its message ("canceled"), silently defeating this guard and
        // letting a routine, expected cancellation surface as a
        // visible "canceled" error toast via refresh()'s own catch.
        if (axios.isCancel(error)) return;
        throw error;
      }
    },
    [clientFilter, isSupervisor, priorityFilter, messageCategoryFilter]
  );

  // Fetches the next MAIL_TAB_FETCH_SIZE-row batch for a tab that has
  // more rows than what's currently loaded, and appends it — used by
  // the Mail page's "Load more" affordance instead of ever pulling a
  // tab's whole history up front.
  const loadMoreBaseTab = useCallback(
    async (key: BaseTabKey) => {
      baseTabAbortRef.current[key]?.abort();
      const controller = new AbortController();
      baseTabAbortRef.current[key] = controller;
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;
      const alreadyLoaded = rowsByTab[key].length;
      try {
        const result = await getInbox(
          key,
          {
            clientId,
            scope: key === "all" ? "all" : undefined,
            limit: MAIL_TAB_FETCH_SIZE,
            offset: alreadyLoaded,
            priority: priorityFilter === "ALL" ? undefined : priorityFilter,
            category: messageCategoryFilter === "ALL" ? undefined : messageCategoryFilter,
          },
          controller.signal
        );
        setRowsByTab((prev) => ({ ...prev, [key]: [...prev[key], ...result.items] }));
        setTabTotals((prev) => ({ ...prev, [key]: result.total }));
      } catch (error) {
        // axios.isCancel, not error.name/instanceof — client.ts's
        // response interceptor now passes a canceled request through
        // unchanged specifically so this check keeps working; it used
        // to rewrap every rejection into a plain Error first, which
        // erased everything about the original CanceledError except
        // its message ("canceled"), silently defeating this guard and
        // letting a routine, expected cancellation surface as a
        // visible "canceled" error toast via refresh()'s own catch.
        if (axios.isCancel(error)) return;
        throw error;
      }
    },
    [clientFilter, rowsByTab, priorityFilter, messageCategoryFilter]
  );

  const fetchSent = useCallback(async () => {
    const result = await getSent();
    setSentItems(result.items.map(sentItemToInboxItem));
  }, []);

  const fetchDrafts = useCallback(async () => {
    const result = await getDrafts();
    setDraftItems(result.items.map(draftItemToInboxItem));
  }, []);

  const fetchMyTicketedClaims = useCallback(async () => {
    const result = await getInbox("ticketed", { assignedToMe: true });
    setMyTicketedClaims(result.items);
  }, []);

  const fetchSystemMail = useCallback(async () => {
    setIsSystemLoading(true);
    try {
      const result = await getNotifications({ types: SYSTEM_NOTIFICATION_TYPES, limit: 100 });
      setSystemNotifications(result.items);
    } finally {
      setIsSystemLoading(false);
    }
  }, []);

  const fetchKey = useCallback(
    (key: LoadKey) => {
      if (key === "sent") return fetchSent();
      if (key === "drafts") return fetchDrafts();
      if (key === "system") return fetchSystemMail();
      if (key === "mineTicketed") return fetchMyTicketedClaims();
      return fetchBaseTab(key);
    },
    [fetchBaseTab, fetchSent, fetchDrafts, fetchSystemMail, fetchMyTicketedClaims]
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

      // A client/priority/category filter change invalidates every
      // previously-loaded tab's cached data (it was scoped to the old
      // filters) — start this refresh as if nothing had been fetched
      // yet, same as the very first load.
      const filterSignature = `${clientFilter}|${priorityFilter}|${messageCategoryFilter}`;
      if (prevClientFilterRef.current !== filterSignature) {
        loadedKeysRef.current = new Set();
        prevClientFilterRef.current = filterSignature;
      }

      // Which tabs need (re)fetching this round — every tab already
      // visited (so previously-seen data stays fresh after a
      // mutation), plus whichever tab is active right now (covers the
      // very first load, before anything's been marked loaded).
      // Computed up front (synchronously) so these fetches can join
      // the same fan-out as the sidebar chrome below, instead of
      // waiting for it to resolve first.
      const keysToRefresh = new Set(loadedKeysRef.current);
      baseKeysForView(activeViewRaw).forEach((key) => keysToRefresh.add(key));
      keysToRefresh.forEach((key) => loadedKeysRef.current.add(key));

      // Folders (this agent's own custom mail folders) don't depend
      // on `clientFilter` at all, so they're only fetched once, on
      // the true first load, not every time the filter changes.
      // Clients/categories are no longer fetched here at all — see
      // this hook's own top-of-file comment on chromeLoadedRef. Real
      // Pending/Replied/Ticketed/Archived/All counts and every tab's
      // actual row data genuinely do depend on `clientFilter`, so
      // those still fire every refresh. All of it still fires in one
      // fan-out (two Promise.all groups nested inside an outer one,
      // purely to keep the first group's tuple typing) — the active
      // tab's data used to only start loading after the sidebar
      // chrome round finished, an avoidable serial round-trip on
      // every load.
      const shouldLoadChrome = !chromeLoadedRef.current;
      const [[folderList, viewCounts]] =
        await Promise.all([
          Promise.all([
            shouldLoadChrome ? listMailFolders() : Promise.resolve(null),
            getViewCounts(clientId),
          ]),
          Promise.all(Array.from(keysToRefresh).map((key) => fetchKey(key))),
        ]);

      if (folderList) {
        setFolders(folderList);
        chromeLoadedRef.current = true;
      }
      setBaseViewCounts(viewCounts);
    } catch (error) {
      pushToast(
        error instanceof Error ? error.message : "Failed to load inbox.",
        "error"
      );
    } finally {
      setIsLoading(false);
    }
  }, [pushToast, clientFilter, activeViewRaw, fetchKey, priorityFilter, messageCategoryFilter]);

  // A lighter alternative to refresh() for after a single mutation
  // (tag/folder/draft-send/discard/compose) — re-pulls the cheap view
  // count aggregate plus only the tab(s) the mutation actually
  // affects (always including whatever's currently on screen),
  // instead of every tab visited so far this session. Any other
  // already-loaded tab is invalidated rather than eagerly re-fetched,
  // so it lazily refetches (see ensureLoaded) the next time the agent
  // actually switches back to it — this keeps what's visible right
  // now correct without every tab paying for one mutation's cost
  // immediately.
  const refreshAfterMutation = useCallback(
    async (extraKeys: LoadKey[] = []) => {
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;
      const keysToRefetchNow = new Set([...baseKeysForView(activeViewRaw), ...extraKeys]);

      loadedKeysRef.current.forEach((key) => {
        if (!keysToRefetchNow.has(key)) loadedKeysRef.current.delete(key);
      });
      keysToRefetchNow.forEach((key) => loadedKeysRef.current.add(key));

      const [viewCounts] = await Promise.all([
        getViewCounts(clientId),
        Promise.all(Array.from(keysToRefetchNow).map((key) => fetchKey(key))),
      ]);
      setBaseViewCounts(viewCounts);
    },
    [clientFilter, activeViewRaw, fetchKey]
  );

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientFilter, priorityFilter, messageCategoryFilter]);

  // Lazy-load a view/tab's data the first time the agent actually
  // switches to it.
  useEffect(() => {
    ensureLoaded(baseKeysForView(activeViewRaw));
  }, [activeViewRaw, ensureLoaded]);

  async function openThread(interactionId: string) {
    const requestId = ++openThreadRequestIdRef.current;
    setOpeningId(interactionId);
    const result = await runOpen(interactionId);
    if (requestId !== openThreadRequestIdRef.current) return;
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
      await refreshAfterMutation();
    }
    return Boolean(result);
  }

  async function assignFolder(interactionId: string, folderId: string | null) {
    const result = await runUpdateFolder(interactionId, folderId);
    if (result) {
      if (selectedEmail?.interaction_id === interactionId) {
        setSelectedEmail({ ...selectedEmail, folder_id: result.folder_id });
      }
      await refreshAfterMutation();
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
    // A send always clears the draft and adds a sent item, regardless
    // of which tab is currently active — refresh both explicitly on
    // top of whatever's on screen.
    if (result) await refreshAfterMutation(["drafts", "sent"]);
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
      await refreshAfterMutation(["drafts"]);
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
      await refreshAfterMutation(["sent"]);
    }
    return result;
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
  // De-duped by interaction_id: `pending`/`replied` are two
  // independently-fetched arrays (parallel requests in refresh()), so
  // an item whose status flips between those two fetches could
  // otherwise land in both and duplicate here. `myTicketedClaims`
  // comes from its own server-scoped ("assigned_to_me") fetch, so it
  // never needs the `claimed_by` filter the pre-ticket half does —
  // once ticketed, "claimed" means "the ticket is assigned to me,"
  // not the pre-ticket `claimed_by` field.
  const mine = Array.from(
    new Map(
      [
        ...[...rowsByTab.pending, ...rowsByTab.replied].filter(
          (item) => item.claimed_by === currentUser?.user_id
        ),
        ...myTicketedClaims,
      ].map((item) => [item.interaction_id, item])
    ).values()
  );

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
    // Never actually read for rendering (InboxPage branches to
    // SystemMailList/SystemMailDetailsView, backed by
    // `systemNotifications` directly, before touching filteredItems
    // below) — present only so this record stays total over
    // MailViewKey and hasMore/loadMore's lookups below never crash.
    system: [],
  };

  // Pending/Replied/Ticketed/Archived/All come from the eager
  // aggregate query (accurate even before that tab's row data has
  // been fetched); Unassigned/Mine/Sent/Drafts are narrower derived
  // views with no aggregate of their own, so their badge counts
  // reflect whatever's actually been loaded so far. System's count is
  // deliberately unread-count (not total), matching the topbar bell's
  // own "badge = needs attention" convention, not the other tabs'
  // "badge = how many items" one.
  const viewCounts: Record<MailViewKey, number> = {
    ...baseViewCounts,
    unassigned: unassigned.length,
    mine: mine.length,
    sent: sentItems.length,
    drafts: draftItems.length,
    system: systemNotifications.filter((n) => !n.is_read).length,
  };

  const filteredItems = applyFilters(rowsByView[activeViewRaw]);

  const managedClientCount = currentUser
    ? clients.filter((c) => c.account_manager_id === currentUser.user_id).length
    : 0;

  // Whether the currently active view's underlying base tab(s) have
  // more rows on the server than what's loaded so far — false for
  // Sent/Drafts/mineTicketed (all kept unbounded; personal, inherently
  // small lists).
  const hasMore = baseKeysForView(activeViewRaw).some((key) => {
    if (key === "sent" || key === "drafts" || key === "system" || key === "mineTicketed") return false;
    return rowsByTab[key].length < tabTotals[key];
  });

  // Fetches the next batch for whichever of the active view's base
  // tab(s) actually have more rows waiting server-side — the Mail
  // page's explicit "Load more" action, so a tab's full history is
  // only ever pulled on demand instead of up front.
  const loadMore = useCallback(async () => {
    const keys = baseKeysForView(activeViewRaw).filter(
      (key): key is BaseTabKey =>
        key !== "sent" &&
        key !== "drafts" &&
        key !== "system" &&
        key !== "mineTicketed" &&
        rowsByTab[key].length < tabTotals[key]
    );
    if (keys.length === 0) return;
    await Promise.all(keys.map((key) => loadMoreBaseTab(key)));
  }, [activeViewRaw, rowsByTab, tabTotals, loadMoreBaseTab]);

  const selectSystemNotification = useCallback((notification: NotificationItem) => {
    setSelectedSystemNotification(notification);
  }, []);

  const clearSelectedSystemNotification = useCallback(() => {
    setSelectedSystemNotification(null);
  }, []);

  // Optimistically updates local state instead of re-fetching the
  // whole System folder — same pattern as updateTags/assignFolder
  // above for the regular Mail list.
  const markSystemNotificationRead = useCallback(async (notificationId: string) => {
    const updated = await markNotificationRead(notificationId);
    setSystemNotifications((prev) =>
      prev.map((n) => (n.notification_id === notificationId ? updated : n))
    );
    setSelectedSystemNotification((prev) =>
      prev?.notification_id === notificationId ? updated : prev
    );
    return updated;
  }, []);

  return {
    isSupervisor,
    isLoading,
    openingId,
    openedIds,
    clients,
    clientFilter,
    setClientFilter,
    priorityFilter,
    setPriorityFilter,
    messageCategoryFilter,
    setMessageCategoryFilter,
    timeFilter,
    setTimeFilter,
    search,
    setSearch,
    activeView: activeViewRaw,
    setActiveView,
    viewCounts,
    filteredItems,
    hasMore,
    loadMore,
    managedClientCount,
    refresh,
    openThread,
    selectedEmail,
    folders,
    categories,
    updateTags,
    assignFolder,
    saveDraftMessage,
    sendDraftMessage,
    discardDraftMessage,
    uploadDraftAttachment,
    removeDraftAttachment,
    composeEmail,
    isComposing,
    systemNotifications,
    isSystemLoading,
    selectedSystemNotification,
    selectSystemNotification,
    clearSelectedSystemNotification,
    markSystemNotificationRead,
  };
}
