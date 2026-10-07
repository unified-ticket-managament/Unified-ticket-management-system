"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Flag,
  Mail,
  MailOpen,
  Pin,
  Paperclip,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Undo2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { cn } from "@/lib/utils";
import { useSettingsStore } from "@/store/settings-store";
import { TIME_FILTERS, type TimeFilterKey } from "@tw/hooks/useMailInbox";
import { formatRelativeTime } from "@/lib/utils";
import type { CategoryResponse, ClientResponse, InboxItem, MailFolder, SLAPolicyResponse, TicketPriority } from "@tw/types";
import { ContextMenu, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { MessageActionsMenu } from "@tw/components/mail/MessageActionsMenu";
import { MessageContextMenuContent } from "@tw/components/mail/MessageContextMenu";
import { MailSelectionBar } from "@tw/components/mail/MailSelectionBar";
import { useMailBulk } from "@tw/components/mail/MailBulkContext";
import { resolveContextTarget, resolveRowClick } from "@tw/lib/mailSelection";
import { rowClientLabel, rowSender, rowSubject, readToggleLabel } from "@tw/lib/messageRow";
import { buildMessageMenu, hasMessageMenu, type MessageActionKey, type MessageActionRow } from "@tw/lib/messageActions";
import { MailEmptyState } from "@tw/components/mail/MailEmptyState";
import { listSlaPolicies } from "@tw/api/sla";
import { getInteractionThread } from "@tw/api/interaction";
import {
  classifyTier,
  computeElapsedFraction,
  computeFirstResponseDueAt,
  SLA_TIER_LABEL,
  type SlaTier,
} from "@tw/lib/slaMath";
import { messageSender, summarize } from "@tw/lib/interactionMeta";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import { mergedClientFilterOptions } from "@tw/lib/clientFilter";
import type { InteractionResponse } from "@tw/types";

type SortKey = "newest" | "oldest" | "sender";
// Collapsed (▶) shows the sender/subject/preview row as before, plus a
// "N messages" toggle beneath it (from InboxItem.reply_count, already
// returned by GET /inbox and previously unused here — no extra fetch).
// Expanded (▼) lazy-fetches that one thread's full message list via the
// existing GET /interactions/{id}/thread endpoint, once per thread, on
// first expand only — never eagerly for every visible row. Rendered as
// additional <li> rows beneath the message's own row (not an overlay on
// top of it), so none of this row's existing checkbox/⋮-menu absolute-
// overlay positioning needs to change.
type ThreadCacheEntry = InteractionResponse[] | "loading" | "error";
type SlaRiskFilter = "ALL" | SlaTier;

// The only valid "Messages per page" choices — kept in sync with
// settings-store.ts's mailMessagesPerPage default (50) and its own
// top-of-file comment pointing back here.
const PAGE_SIZE_OPTIONS = [50, 100, 200, 500] as const;
type MessageListPageSize = (typeof PAGE_SIZE_OPTIONS)[number];

function isValidPageSize(value: number): value is MessageListPageSize {
  return (PAGE_SIZE_OPTIONS as readonly number[]).includes(value);
}

// A generous, purely-defensive ceiling on how many on-demand batches
// "Last Page" will fetch in one go (see goToLast below) — not a real
// limit tied to any actual inbox size, just a runaway-fetch safety
// net for a pathologically large result set.
const MAX_LOAD_MORE_BATCHES_FOR_LAST_PAGE = 50;

// Coarser than the single-message countdown's 1s tick (SlaFirstResponseBadge/
// useFirstResponseCountdown) — this drives a whole list's sort/badges, not a
// live per-second countdown, so a cheaper refresh is enough to stay honest.
const TIER_REFRESH_INTERVAL_MS = 30_000;

const STATUS_META: Record<string, { label: string; variant: "warning" | "success" | "secondary" }> = {
  PENDING: { label: "Pending", variant: "warning" },
  ASSIGNED: { label: "Replied", variant: "success" },
  IGNORED: { label: "Archived", variant: "secondary" },
};

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
  CRITICAL: "destructive",
};

// Prefers the real, persisted is_read (message_read_receipts) once
// present — falls back to the client-only openedIds Set only for a
// row shape that doesn't carry is_read at all (the OTP-forward
// synthetic rows built from a Notification, out of scope for this
// change — they're backed by NotificationItem.is_read separately).
function isItemUnread(item: InboxItem, openedIds: Set<string>): boolean {
  if (item.is_read !== undefined) return !item.is_read;
  return !openedIds.has(item.open_interaction_id ?? item.interaction_id);
}

function statusMeta(item: InboxItem): { label: string; variant: "warning" | "success" | "secondary" | "default" } {
  if (item.ticket_id) return { label: "Ticketed", variant: "default" };
  return STATUS_META[item.status] ?? { label: item.status, variant: "secondary" };
}

// First 80–120 characters of the latest message as a row preview —
// empty (not a placeholder) when there's nothing to show.
const PREVIEW_MAX_LENGTH = 110;
// toggleRead does not depend on permissions; only the labels are used.
const NO_PERMS = { replyExternal: false, createTicket: false, attachToTicket: false, archive: false, moveToFolder: false };

function previewOf(message: string | null | undefined): string {
  const trimmed = message?.trim();
  if (!trimmed) return "";
  return trimmed.length > PREVIEW_MAX_LENGTH ? `${trimmed.slice(0, PREVIEW_MAX_LENGTH).trimEnd()}…` : trimmed;
}

function initialsOf(name: string): string {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return initials || "?";
}

interface MessageListProps {
  folderLabel: string;
  items: InboxItem[];
  isLoading: boolean;
  // "standalone" (default) keeps this component's own card chrome
  // (rounded/border/shadow, fixed viewport-relative height) for any
  // caller rendering it on its own. "panel" — used by the Outlook-
  // style three-panel Mail workspace, see InboxPage.tsx/
  // MailWorkspaceLayout.tsx — drops that chrome and fills its parent
  // panel's own height instead, since the workspace's outer container
  // already supplies the card look for the whole three-panel area.
  variant?: "standalone" | "panel";
  // The row currently open in the reading pane (Panel 3), matched
  // against each row's own `open_interaction_id ?? interaction_id` —
  // renders a highlighted state so the open message stays visually
  // identifiable in the list, Outlook-style. Omitted/null renders no
  // highlight, unchanged from before this prop existed.
  selectedId?: string | null;
  // The one message within the currently-open thread that's individually
  // highlighted/scrolled-to in the reading pane (see MessageDetailsView) —
  // null means no child message is singled out (the parent row's own
  // `selectedId` highlight above is the only one active). Matched against
  // each thread message's own interaction_id, same id space `onOpenMessage`
  // below is called with.
  selectedMessageId?: string | null;
  // True only after a genuine (non-cancel) fetch failure for whatever
  // is currently backing `items` — lets the empty-state branch below
  // distinguish "the request failed" from "it genuinely returned zero
  // rows," so an API error never renders as a plausible-looking empty
  // inbox. Optional/defaulted false so this stays additive for any
  // caller not yet passing it.
  isError?: boolean;
  openingId: string | null;
  openedIds: Set<string>;
  search: string;
  onSearchChange: (value: string) => void;
  timeFilter: TimeFilterKey;
  onTimeFilterChange: (value: TimeFilterKey) => void;
  clientFilter: string;
  onClientFilterChange: (value: string) => void;
  // Priority/Category are real, indexed backend filters (GET /inbox)
  // — `items` arrives already filtered by both, so this component no
  // longer filters on them itself (see the removed local state this
  // replaced). `availableCategories` is the full, session-wide
  // category list (WorkflowContext), not derived from `items` — a
  // list narrowed by the current filter can't also be the source of
  // that filter's own dropdown options.
  priorityFilter: string;
  onPriorityFilterChange: (value: string) => void;
  categoryFilter: string;
  onCategoryFilterChange: (value: string) => void;
  availableCategories: CategoryResponse[];
  // Category options for the merged "All Clients" dropdown specifically
  // — optionally wider than availableCategories (e.g. Team Lead/Staff
  // get the full org-wide category list here, same convention Compose's
  // own "From" picker already uses, while availableCategories above
  // stays scoped to whatever the standalone "Any category" ticket-type
  // filter needs). Falls back to availableCategories when omitted, so
  // no other caller needs updating.
  clientFilterCategories?: CategoryResponse[];
  clients: ClientResponse[];
  onOpen: (interactionId: string) => void;
  // Clicking an individual thread-child message (once a conversation is
  // expanded) — opens its root thread if not already open, then
  // highlights/scrolls to this one specific message in the reading pane.
  // Optional so this stays additive for any caller not yet passing it.
  onOpenMessage?: (rootInteractionId: string, messageId: string) => void;
  // Re-clicking an already-open parent row while a child message is
  // highlighted switches back to "whole conversation" (no refetch).
  onDeselectMessage?: () => void;
  // Double-clicking a row opens the same message in a full-screen
  // view (Outlook-style), on top of the existing single-click
  // behavior above — optional so this stays additive for any caller
  // not yet passing it.
  onOpenFullScreen?: (interactionId: string) => void;
  onCompose: () => void;
  onRefresh: () => void;
  // Whether the active view's underlying tab(s) have more rows on the
  // server than what's currently in `items` — this list is fetched in
  // bounded batches now (see useMailInbox's MAIL_TAB_FETCH_SIZE)
  // rather than a tab's entire history up front. Surfaced here only as
  // a "+" in the message count below, not wired to any load-more
  // action from this component.
  hasMore: boolean;
  onLoadMore: () => Promise<void>;
  // Per-row "More actions" (⋮) menu — optional so this stays additive
  // for any caller not yet passing them; the menu only renders when
  // all four are provided. See MessageActionsMenu.tsx.
  folders?: MailFolder[];
  onMessageAction?: (interactionId: string, action: MessageActionKey) => void;
  onMarkRead?: (interactionId: string) => void;
  onMarkUnread?: (interactionId: string) => void;
  onAssignFolder?: (interactionId: string, folderId: string | null) => Promise<boolean>;
}

export function MessageList({
  folderLabel,
  items,
  isLoading,
  isError = false,
  variant = "standalone",
  selectedId = null,
  selectedMessageId = null,
  openingId,
  openedIds,
  search,
  onSearchChange,
  timeFilter,
  onTimeFilterChange,
  clientFilter,
  onClientFilterChange,
  priorityFilter,
  onPriorityFilterChange,
  categoryFilter,
  onCategoryFilterChange,
  availableCategories,
  clientFilterCategories,
  clients,
  onOpen,
  onOpenMessage,
  onDeselectMessage,
  onOpenFullScreen,
  onCompose,
  onRefresh,
  hasMore,
  onLoadMore,
  folders,
  onMessageAction,
  onMarkRead,
  onMarkUnread,
  onAssignFolder,
}: MessageListProps) {
  const [sort, setSort] = useState<SortKey>("newest");
  // Unread/attachments have no backend filter equivalent (unread
  // isn't queryable server-side yet — see InboxItemResponse.is_read's
  // own docstring — and has_attachments is a per-row derived flag,
  // not a real column) — these stay client-side, over whatever page
  // is currently loaded, same as before.
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [attachmentsOnly, setAttachmentsOnly] = useState(false);
  // Like unread/attachments: narrows the rows already loaded, using the
  // caller's own is_flagged (GET /inbox?flagged=true is the server-side
  // equivalent for callers that want the full filtered set).
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [slaRiskFilter, setSlaRiskFilter] = useState<SlaRiskFilter>("ALL");

  // Pagination — operates on `filtered` (this list's own current
  // result set, after every existing filter/sort), not on `items`
  // directly, so it stays correct for whichever folder/view/search/
  // filter combination is currently active. Page size is a persisted,
  // device-local preference (shared across every MessageList instance
  // via the store); the current page number is local, per-instance
  // state — deliberately not persisted, only the size preference is.
  const persistedPageSize = useSettingsStore((s) => s.mailMessagesPerPage);
  const setPersistedPageSize = useSettingsStore((s) => s.setMailMessagesPerPage);
  const pageSize: MessageListPageSize = isValidPageSize(persistedPageSize) ? persistedPageSize : 50;
  const [page, setPage] = useState(1);
  // Row whose ⋮ menu is open — keeps its hover overlay visible even
  // though the pointer has moved onto the menu.
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  // Outlook-style per-conversation expand/collapse — keyed by the same
  // openId every other per-row action here uses. threadCache persists
  // for this component's lifetime (not cleared on refresh/filter
  // change) purely as a display-preview cache; it's never read by
  // anything that needs to be authoritative.
  const [expandedThreadIds, setExpandedThreadIds] = useState<Set<string>>(new Set());
  const [threadCache, setThreadCache] = useState<Record<string, ThreadCacheEntry>>({});

  async function toggleThreadExpanded(openId: string) {
    setExpandedThreadIds((prev) => {
      const next = new Set(prev);
      if (next.has(openId)) next.delete(openId);
      else next.add(openId);
      return next;
    });
    if (threadCache[openId]) return;
    setThreadCache((prev) => ({ ...prev, [openId]: "loading" }));
    try {
      const thread = await getInteractionThread(openId);
      setThreadCache((prev) => ({ ...prev, [openId]: thread.ordered_thread }));
    } catch {
      setThreadCache((prev) => ({ ...prev, [openId]: "error" }));
    }
  }
  // True while "Last Page" is fetching additional batches to find the
  // real final page — see goToLast below.
  const [isJumpingToLast, setIsJumpingToLast] = useState(false);
  // True while "Next"/"Last" triggered exactly one on-demand batch
  // fetch to fill the page being navigated to.
  const [isLoadingNextBatch, setIsLoadingNextBatch] = useState(false);
  // Mirrors the `hasMore` prop for goToLastPage's loop below — an
  // async function's own local reference to a prop captured at call
  // time never sees later renders' updated value, so the loop reads
  // this ref (kept current via the effect right after it) instead of
  // closing over the stale `hasMore` parameter directly.
  const hasMoreRef = useRef(hasMore);
  useEffect(() => {
    hasMoreRef.current = hasMore;
  }, [hasMore]);

  // First Response SLA tier, computed client-side — no dedicated read
  // endpoint exists (same reason SlaFirstResponseBadge/
  // useFirstResponseCountdown recompute it), so this fetches the one
  // shared MEDIUM target once for the whole list rather than per row.
  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    listSlaPolicies()
      .then((data) => {
        if (!cancelled) setPolicies(data);
      })
      .catch(() => {
        // No policy data -> firstResponseTierFor returns null for
        // every row, same "just don't render/sort/filter by it yet"
        // degrade-safe behavior as the single-message badge.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), TIER_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, []);

  const targetMinutes = policies?.find((p) => p.priority === "MEDIUM")?.first_response_target_minutes ?? null;

  // Only a still-pending, not-yet-ticketed message has a First
  // Response clock to show — same gate SlaFirstResponseBadge's own
  // `enabled` prop already uses. A ticketed row's relevant clock is
  // Resolution SLA instead, tracked on the Tickets page, not here.
  //
  // Prefers the row's real, DB-backed `first_response_sla` state when
  // present: a COMPLETED clock returns null (a stopped clock is never
  // "at risk" of anything — matches this list's existing convention
  // of rendering no badge at all for a healthy/non-risk row), and a
  // still-PENDING clock classifies off its real `elapsed_fraction`
  // instead of a client-guessed one. Only falls back to the client-
  // computed estimate when `first_response_sla` is absent (a row
  // returned before this field existed).
  function firstResponseTierFor(item: InboxItem): SlaTier | null {
    if (item.ticket_id || item.status !== "PENDING") return null;

    if (item.first_response_sla) {
      if (item.first_response_sla.status === "COMPLETED") return null;
      return classifyTier(item.first_response_sla.elapsed_fraction);
    }

    if (targetMinutes == null) return null;
    const dueAt = computeFirstResponseDueAt(item.received_at, targetMinutes);
    return classifyTier(computeElapsedFraction({ dueAt, targetMinutes, now }));
  }

  // Priority/category are now applied server-side (GET /inbox) —
  // `items` already reflects both filters, so unread/attachments/SLA
  // risk and sort are applied here. SLA risk is filter-only — it no
  // longer also reorders the list ahead of the user's chosen sort,
  // since pinning Escalated/Breached/At Risk mail to the top buried
  // genuinely new incoming mail underneath older escalated items.
  const filtered = useMemo(() => {
    // De-duped by interaction_id before anything else — `items` can
    // legitimately contain the same row twice once pagination's
    // "Next"/"Last" actually exercises the pre-existing load-more
    // path (see onLoadMore below): offset-based pagination re-fetches
    // a shifted window if a new email arrives between batches, and
    // the appended batch can re-include a row already present from an
    // earlier one. Same fix shape as useMailInbox.ts's own inboxAll/
    // mine construction (Map keyed by interaction_id) — this is the
    // one path that array doesn't already cover, since load-more had
    // no UI trigger before this pagination feature added one.
    let rows = Array.from(new Map(items.map((item) => [item.interaction_id, item])).values());
    if (unreadOnly) rows = rows.filter((item) => isItemUnread(item, openedIds));
    if (attachmentsOnly) rows = rows.filter((item) => item.has_attachments);
    if (flaggedOnly) rows = rows.filter((item) => item.is_flagged);
    if (slaRiskFilter !== "ALL") {
      rows = rows.filter((item) => firstResponseTierFor(item) === slaRiskFilter);
    }

    // Pinned mail always leads (the server already pages that way); the
    // chosen sort then orders within the pinned and unpinned groups.
    return [...rows].sort((a, b) => {
      if (Boolean(a.is_pinned) !== Boolean(b.is_pinned)) return a.is_pinned ? -1 : 1;
      if (sort === "sender") {
        const aName = a.category_id ? a.category_name || "" : a.client_name;
        const bName = b.category_id ? b.category_name || "" : b.client_name;
        return aName.localeCompare(bName);
      }
      const aTime = new Date(a.latest_at ?? a.received_at).getTime();
      const bTime = new Date(b.latest_at ?? b.received_at).getTime();
      return sort === "oldest" ? aTime - bTime : bTime - aTime;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, unreadOnly, attachmentsOnly, flaggedOnly, sort, openedIds, slaRiskFilter, targetMinutes, now]);

  // `filtered.length` is "everything currently loaded and matching
  // every active filter" — the real total once `hasMore` is false, or
  // a known-so-far lower bound while more batches are still fetchable
  // on demand (see goToNext/goToLast below, and the "+" suffix in the
  // render further down, matching this file's own pre-existing
  // {hasMore ? "+" : ""} convention on the message count).
  const totalPagesKnown = Math.max(1, Math.ceil(filtered.length / pageSize));
  const isOnLastKnownPage = page >= totalPagesKnown;
  // goToLastPage needs the post-fetch result count once its own fetch
  // loop finishes, not the count captured when it was first called —
  // same stale-closure problem/fix as hasMoreRef above.
  const filteredLengthRef = useRef(filtered.length);
  useEffect(() => {
    filteredLengthRef.current = filtered.length;
  }, [filtered.length]);
  const pageStartIndex = (page - 1) * pageSize;
  const pageItems = useMemo(
    () => filtered.slice(pageStartIndex, pageStartIndex + pageSize),
    [filtered, pageStartIndex, pageSize]
  );
  const pageEndIndex = pageStartIndex + pageItems.length;

  // ---- Multi-select (state lives in MailBulkProvider; null → no bulk) ----
  const bulk = useMailBulk();
  const bulkClear = bulk?.clear;
  const bulkPrune = bulk?.prune;

  // Rows are selectable by the same id every per-message action uses.
  const openIdOf = (item: InboxItem) => item.open_interaction_id ?? item.interaction_id;
  const toActionRow = (item: InboxItem): MessageActionRow => ({
    ...item,
    isUnread: isItemUnread(item, openedIds),
  });
  const visibleSelectableIds = useMemo(
    () => pageItems.filter((item) => hasMessageMenu({ ...item, isUnread: false })).map(openIdOf),
    [pageItems]
  );
  const selectedRows = useMemo(
    () =>
      bulk && bulk.selectedIds.size > 0
        ? filtered
            .filter((item) => bulk.selectedIds.has(openIdOf(item)))
            .map((item) => toActionRow(item))
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [bulk?.selectedIds, filtered, openedIds]
  );

  // A different page / sort / filter / search is a different result set —
  // the selection does not follow it (no persistent cross-page selection).
  useEffect(() => {
    bulkClear?.();
  }, [
    bulkClear,
    page,
    pageSize,
    sort,
    unreadOnly,
    attachmentsOnly,
    slaRiskFilter,
    search,
    timeFilter,
    clientFilter,
    priorityFilter,
    categoryFilter,
  ]);

  // A refetch can drop rows (archived, deleted, ticketed): keep only the
  // ones still loaded so a stale id is never sent.
  useEffect(() => {
    bulkPrune?.(items.map(openIdOf));
  }, [bulkPrune, items]);

  // Resets to page 1 whenever the page size changes or any filter/
  // sort this component owns changes — `items` itself (the folder/
  // view's underlying data, or a search/priority/category/time-filter
  // change applied upstream in useMailInbox) is included so switching
  // folders or changing an upstream filter also resets, matching the
  // pre-existing "resets to page 1 on folder/search/filter change"
  // convention this Mail page has always followed.
  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageSize, items, unreadOnly, attachmentsOnly, flaggedOnly, sort, slaRiskFilter]);

  // Separate safety net for section 13's "data changed under you"
  // case (e.g. a mutation removes a row from the current page while
  // the user hasn't touched any filter/page-size control) — clamps
  // down to the nearest valid page instead of resetting all the way
  // to 1, so an in-place data change never strands the user on an
  // empty page.
  useEffect(() => {
    setPage((current) => Math.min(current, totalPagesKnown));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPagesKnown]);

  // Keeps the CURRENT page topped up with real data — the actual fix
  // for "selecting 200/500 per page doesn't display that many": the
  // app only ever fetches MAIL_TAB_FETCH_SIZE (200) rows up front, so
  // without this, choosing a page size (or a page) that needs more
  // than what's already loaded would just silently render whatever's
  // available instead of the requested count. Fires on page/pageSize
  // change (and again each time a fetch it triggered lands and
  // `filtered.length` grows, since that's this effect's own
  // dependency) until either the current page is fully filled or
  // `hasMore` goes false — the same "keep fetching bounded batches
  // until satisfied" idea as goToLastPage, just driven by whichever
  // page is currently on screen rather than a one-off jump. Skips
  // entirely while goToNextPage/goToLastPage already have their own
  // fetch in flight (isLoadingNextBatch/isJumpingToLast), so this
  // never races or double-fetches against them. Guarded against a
  // persistent fetch failure retrying in a tight loop: unlike
  // goToNextPage/goToLastPage (one-shot click handlers, so a failure
  // just leaves the button re-clickable), this effect re-fires
  // reactively — without tracking a failed attempt, a rejected
  // onLoadMore() would immediately retry the exact same fetch forever
  // (filtered.length/hasMore never having changed to make the guard
  // above false). Keyed on the state that would have to change for a
  // retry to be worth attempting again; a later successful fetch
  // (e.g. a manual refresh) changes filtered.length and naturally
  // clears this.
  const lastFailedAttemptKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (isLoadingNextBatch || isJumpingToLast) return;
    const rowsNeededForCurrentPage = page * pageSize;
    if (filtered.length >= rowsNeededForCurrentPage || !hasMore) return;
    const attemptKey = `${page}:${pageSize}:${filtered.length}`;
    if (lastFailedAttemptKeyRef.current === attemptKey) return;
    setIsLoadingNextBatch(true);
    onLoadMore()
      .catch(() => {
        lastFailedAttemptKeyRef.current = attemptKey;
      })
      .finally(() => setIsLoadingNextBatch(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize, filtered.length, hasMore, isLoadingNextBatch, isJumpingToLast]);

  function goToFirstPage() {
    setPage(1);
  }

  function goToPreviousPage() {
    setPage((current) => Math.max(1, current - 1));
  }

  // Only fetches when the page being navigated to needs rows beyond
  // what's already loaded — reuses the existing bounded batch fetch
  // (onLoadMore/hasMore, see useMailInbox's MAIL_TAB_FETCH_SIZE)
  // rather than ever pulling the whole result set up front.
  async function goToNextPage() {
    const needsMoreData = page * pageSize >= filtered.length && hasMore;
    if (needsMoreData) {
      setIsLoadingNextBatch(true);
      try {
        await onLoadMore();
      } finally {
        setIsLoadingNextBatch(false);
      }
    }
    setPage((current) => current + 1);
  }

  // Jumps to the true final page — if more data is fetchable, fetches
  // it in bounded batches (same MAIL_TAB_FETCH_SIZE-sized calls as
  // "Next"/the existing Load More affordance) until hasMore genuinely
  // goes false or the defensive cap above is hit, then lands on the
  // real last page rather than an interim "last known so far" one.
  async function goToLastPage() {
    if (!hasMoreRef.current) {
      setPage(totalPagesKnown);
      return;
    }
    setIsJumpingToLast(true);
    try {
      let batches = 0;
      while (hasMoreRef.current && batches < MAX_LOAD_MORE_BATCHES_FOR_LAST_PAGE) {
        await onLoadMore();
        // Yield one macrotask so React can commit the re-render the
        // fetch's setState calls scheduled (and this component's own
        // hasMoreRef/filteredLengthRef-syncing effects can run) before
        // the loop re-checks hasMoreRef — without this, the just-
        // awaited fetch's result wouldn't be reflected yet and every
        // iteration would look like it still "has more," fetching far
        // more than actually needed.
        await new Promise((resolve) => setTimeout(resolve, 0));
        batches += 1;
      }
      const freshTotalPages = Math.max(1, Math.ceil(filteredLengthRef.current / pageSize));
      setPage(freshTotalPages);
    } finally {
      setIsJumpingToLast(false);
    }
  }

  const activeFilterCount = [
    priorityFilter !== "ALL",
    unreadOnly,
    attachmentsOnly,
    flaggedOnly,
    categoryFilter !== "ALL",
    timeFilter !== "ALL",
    slaRiskFilter !== "ALL",
  ].filter(Boolean).length;

  const { activeClients, categoryOptions: clientFilterCategoryOptions } = useMemo(
    () => mergedClientFilterOptions(clients, clientFilterCategories ?? availableCategories),
    [clients, availableCategories, clientFilterCategories]
  );

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden",
        variant === "panel"
          ? "h-full"
          : "rounded-xl border border-border bg-card shadow-card lg:h-[calc(100vh-7rem)]"
      )}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-card px-4 py-3.5">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-semibold text-foreground">{folderLabel}</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onRefresh} aria-label="Refresh" className="h-8 w-8">
          <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
        </Button>
      </div>

      <div className="sticky top-[57px] z-10 flex flex-wrap items-center gap-2 border-b border-border bg-card px-4 py-2.5">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search sender, subject, or message..."
            className="h-9 pl-8 text-[13px]"
          />
        </div>

        <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
          <SelectTrigger className="h-9 w-[132px] text-[13px]">
            <SelectValue placeholder="Sort" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="newest">Newest first</SelectItem>
            <SelectItem value="oldest">Oldest first</SelectItem>
            <SelectItem value="sender">Sender A–Z</SelectItem>
          </SelectContent>
        </Select>

        <Select value={clientFilter} onValueChange={onClientFilterChange}>
          <SelectTrigger className="h-9 w-[150px] text-[13px]">
            <SelectValue placeholder="Client" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All clients</SelectItem>
            {activeClients.map((client) => (
              <SelectItem key={client.client_id} value={client.client_id}>
                {client.name}
              </SelectItem>
            ))}
            {clientFilterCategoryOptions.map((category) => (
              <SelectItem key={`category-${category.category_id}`} value={category.category_name}>
                {category.category_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-9 gap-1.5 text-[13px]">
              <SlidersHorizontal className="h-3.5 w-3.5" />
              Filters
              {activeFilterCount > 0 && (
                <Badge className="h-4 min-w-[1rem] justify-center px-1 text-[10px]">{activeFilterCount}</Badge>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64 p-3">
            <DropdownMenuLabel className="px-0 py-0 text-xs">Priority</DropdownMenuLabel>
            <Select value={priorityFilter} onValueChange={onPriorityFilterChange}>
              <SelectTrigger className="mt-1.5 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Any priority</SelectItem>
                <SelectItem value="LOW">Low</SelectItem>
                <SelectItem value="MEDIUM">Medium</SelectItem>
                <SelectItem value="HIGH">High</SelectItem>
              </SelectContent>
            </Select>

            <DropdownMenuLabel className="mt-3 px-0 py-0 text-xs">Category</DropdownMenuLabel>
            <Select value={categoryFilter} onValueChange={onCategoryFilterChange}>
              <SelectTrigger className="mt-1.5 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Any category</SelectItem>
                {availableCategories.map((category) => (
                  <SelectItem key={category.category_id} value={category.category_name}>
                    {category.category_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <DropdownMenuLabel className="mt-3 px-0 py-0 text-xs">SLA risk</DropdownMenuLabel>
            <Select value={slaRiskFilter} onValueChange={(v) => setSlaRiskFilter(v as SlaRiskFilter)}>
              <SelectTrigger className="mt-1.5 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Any</SelectItem>
                <SelectItem value="escalated">{SLA_TIER_LABEL.escalated}</SelectItem>
                <SelectItem value="breached">{SLA_TIER_LABEL.breached}</SelectItem>
                <SelectItem value="at_risk">{SLA_TIER_LABEL.at_risk}</SelectItem>
                <SelectItem value="healthy">{SLA_TIER_LABEL.healthy}</SelectItem>
              </SelectContent>
            </Select>

            <DropdownMenuLabel className="mt-3 px-0 py-0 text-xs">Date received</DropdownMenuLabel>
            <Select value={timeFilter} onValueChange={(v) => onTimeFilterChange(v as TimeFilterKey)}>
              <SelectTrigger className="mt-1.5 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIME_FILTERS.map((f) => (
                  <SelectItem key={f.key} value={f.key}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <DropdownMenuSeparator />

            <label className="flex items-center gap-2 py-1 text-xs">
              <Checkbox checked={unreadOnly} onCheckedChange={(v) => setUnreadOnly(Boolean(v))} />
              Unread only
            </label>
            <label className="flex items-center gap-2 py-1 text-xs">
              <Checkbox checked={attachmentsOnly} onCheckedChange={(v) => setAttachmentsOnly(Boolean(v))} />
              Has attachments
            </label>
            <label className="flex items-center gap-2 py-1 text-xs">
              <Checkbox checked={flaggedOnly} onCheckedChange={(v) => setFlaggedOnly(Boolean(v))} />
              Flagged
            </label>

            {activeFilterCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  onPriorityFilterChange("ALL");
                  onCategoryFilterChange("ALL");
                  setUnreadOnly(false);
                  setAttachmentsOnly(false);
                  setFlaggedOnly(false);
                  setSlaRiskFilter("ALL");
                  onTimeFilterChange("ALL");
                }}
                className="mt-2 w-full rounded-md border border-border py-1.5 text-[11.5px] font-medium text-muted-foreground hover:bg-muted"
              >
                Clear all filters
              </button>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {bulk && folders && filtered.length > 0 && (
        <MailSelectionBar
          visibleIds={visibleSelectableIds}
          selectedRows={selectedRows}
          folders={folders}
        />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && filtered.length === 0 ? (
          <WorkflowLoader loading size={56} className="h-full" />
        ) : isError && filtered.length === 0 ? (
          // Distinct from the "genuinely empty" branch below — a
          // failed request must never look like a plausible empty
          // inbox. Reuses MailEmptyState's own layout (no new
          // empty-state design), just different copy/icon and a
          // Refresh action instead of Compose.
          <div className="p-4">
            <MailEmptyState
              onCompose={onCompose}
              icon={AlertCircle}
              title="Couldn't load messages"
              description="Something went wrong loading this view. Try refreshing."
              action={{ label: "Refresh", icon: RefreshCw, onClick: onRefresh }}
            />
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4">
            <MailEmptyState onCompose={onCompose} />
          </div>
        ) : (
          <TooltipProvider delayDuration={300}>
          <ul className="divide-y divide-border">
            {pageItems.map((item) => {
              const openId = item.open_interaction_id ?? item.interaction_id;
              const isUnread = isItemUnread(item, openedIds);
              const status = statusMeta(item);
              const isOpening = openingId === openId;
              const preview = previewOf(item.latest_message);
              const slaTier = firstResponseTierFor(item);
              const isSelected = selectedId != null && openId === selectedId;
              // A CATEGORY-mailbox row has no client — category_id is
              // set instead (see InboxItem's own docstring).
              const isCategoryInbox = !!item.category_id;
              const clientLabel = rowClientLabel(item);
              const sender = rowSender(item);
              const subject = rowSubject(item);
              // Avatar initials follow the primary line (sender).
              const displayName = sender;
              const overlayPinned = menuOpenId === openId;

              const selectable = Boolean(bulk) && hasMessageMenu({ ...item, isUnread });
              const isChecked = selectable && bulk!.selectedIds.has(openId);
              const selectionActive = (bulk?.selectedIds.size ?? 0) > 0;
              const canContextMenu =
                selectable && !!(folders && onMessageAction && onMarkRead && onMarkUnread && onAssignFolder);

              // Outlook-style conversation state for this root — computed
              // here (rather than after rowContent, as before) since the
              // parent row itself now carries both the ▶/▼ toggle and the
              // "N messages" label inline, instead of a separate toggle
              // row beneath it.
              const isThreadExpanded = expandedThreadIds.has(openId);
              const threadEntry = threadCache[openId];
              const totalMessageCount = item.reply_count + 1;
              const hasThread = item.reply_count > 0;

              const rowContent = (
                <>
                  <div
                    className={cn(
                      "flex w-full items-start gap-1 px-4 py-3 text-left transition-all duration-150 hover:z-[1] hover:-translate-y-0.5 hover:bg-muted/60 hover:shadow-sm",
                      isUnread && "bg-primary/[0.03]",
                      isSelected && "bg-primary/10 hover:bg-primary/10",
                      isChecked && "bg-primary/[0.08]",
                      isOpening && "opacity-60"
                    )}
                  >
                    {/* ▶/▼ — expand/collapse ONLY, independent of the
                        parent-row click below (opens the whole
                        conversation) and the checkbox overlay (selection
                        only). A row with no replies gets an equal-width
                        spacer so every avatar still lines up in the same
                        column. */}
                    {hasThread ? (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleThreadExpanded(openId);
                        }}
                        aria-expanded={isThreadExpanded}
                        aria-label={isThreadExpanded ? "Collapse conversation" : "Expand conversation"}
                        className="flex h-9 w-6 flex-none items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        {isThreadExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </button>
                    ) : (
                      <span className="h-9 w-6 flex-none" aria-hidden="true" />
                    )}
                    <button
                      type="button"
                      onClick={(event) => {
                        // Ctrl (Win/Linux) / Cmd (macOS) + Click toggles
                        // this row in the selection and does NOT open it,
                        // so it can't change the reading pane, mark the
                        // thread read, or disturb the rest of the selection.
                        if (selectable && bulk && resolveRowClick(event, bulk.platform) === "toggle") {
                          event.preventDefault();
                          bulk.toggle(openId);
                          return;
                        }
                        // Already open in the reading pane — re-firing
                        // onOpen would just re-run "open thread" (and
                        // its mark-read side effect) for no reason; use
                        // the dedicated Refresh action for that instead.
                        // Same for a row whose open is still in flight.
                        if (isOpening) return;
                        // If a child message is currently highlighted
                        // though, re-clicking the parent still means
                        // something: switch back to the whole-conversation
                        // view without a refetch.
                        if (isSelected) {
                          if (selectedMessageId) onDeselectMessage?.();
                          return;
                        }
                        onOpen(openId);
                      }}
                      onDoubleClick={(event) => {
                        if (selectable && bulk && resolveRowClick(event, bulk.platform) === "toggle") return;
                        onOpenFullScreen?.(openId);
                      }}
                      // Deliberately NOT `disabled` while opening: the
                      // first click of a double-click starts the open,
                      // and a disabled button swallows the second click,
                      // so dblclick would never fire (it then took a
                      // third click to get the window).
                      aria-busy={isOpening || undefined}
                      className="flex flex-1 items-start gap-3 text-left"
                    >
                    <div className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-primary/10 text-[12px] font-semibold text-primary">
                      {initialsOf(displayName)}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        {isUnread && <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-label="Unread" />}
                        <span
                          className={cn(
                            "truncate text-[13.5px]",
                            isUnread ? "font-semibold text-foreground" : "font-normal text-foreground/90"
                          )}
                        >
                          {sender}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-1.5">
                        <p
                          className={cn(
                            "truncate text-[13px]",
                            isUnread ? "font-semibold text-foreground" : "text-foreground/80"
                          )}
                        >
                          {subject}
                        </p>
                        {item.has_attachments && (
                          <Paperclip className="h-3 w-3 flex-none text-muted-foreground" aria-label="Has attachment" />
                        )}
                        {item.is_flagged && (
                          <Flag className="h-3 w-3 flex-none fill-destructive text-destructive" aria-label="Flagged" />
                        )}
                        {item.is_pinned && (
                          <Pin className="h-3 w-3 flex-none fill-primary text-primary" aria-label="Pinned" />
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center justify-between gap-2">
                        <p className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">
                          {clientLabel && (
                            <span className="font-medium text-foreground/70">
                              {isCategoryInbox ? `Category · ${clientLabel}` : clientLabel}
                              {preview ? " · " : ""}
                            </span>
                          )}
                          {preview}
                        </p>
                        {hasThread && (
                          <span className="flex-none whitespace-nowrap text-[11px] text-muted-foreground">
                            {totalMessageCount} message{totalMessageCount === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex min-w-[100px] flex-none flex-col items-end gap-1.5 pl-1">
                      {/* Timestamp keeps its slot; the hover overlay below
                          sits on top of it (opacity only, no reflow). */}
                      <span
                        className={cn(
                          "h-6 whitespace-nowrap text-[11px] leading-6 text-muted-foreground transition-opacity",
                          canContextMenu && "group-hover/row:opacity-0 max-lg:opacity-0",
                          overlayPinned && "opacity-0"
                        )}
                      >
                        {formatRelativeTime(item.latest_at ?? item.received_at)}
                      </span>
                      {/* First Response SLA tier — only a still-pending
                          message has one; a ticketed row's relevant
                          clock is Resolution SLA, shown on the Tickets
                          page instead. On Track isn't shown here, same
                          "only the tiers worth flagging" convention as
                          the Tickets page's own badge. */}
                      {slaTier && slaTier !== "healthy" && <SlaBadge tier={slaTier} />}
                      {item.ticket_priority && (
                        <Badge variant={PRIORITY_VARIANT[item.ticket_priority]} className="text-[10px]">
                          {item.ticket_priority}
                        </Badge>
                      )}
                      <Badge variant={status.variant} className="text-[10px]">
                        {status.label}
                      </Badge>
                    </div>
                    </button>
                  </div>
                  {folders && onMessageAction && onMarkRead && onMarkUnread && onAssignFolder && hasMessageMenu({ ...item, isUnread }) && (
                    <div
                      className={cn(
                        "absolute right-4 top-3 z-[2] flex h-6 items-center gap-0.5 rounded-md bg-background opacity-0 shadow-sm ring-1 ring-border transition-opacity focus-within:opacity-100 group-hover/row:opacity-100 max-lg:opacity-100",
                        overlayPinned && "opacity-100"
                      )}
                    >
                      {bulk?.isTrash ? (
                        // Trash: the only quick action is Restore (same
                        // bulk "restore" path as the toolbar/context menu).
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label="Restore"
                              disabled={bulk.busy}
                              onClick={() => bulk.runBulk("restore", [toActionRow(item)])}
                              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                            >
                              <Undo2 className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>Restore</TooltipContent>
                        </Tooltip>
                      ) : (
                        <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            aria-label={readToggleLabel(buildMessageMenu({ ...item, isUnread }, NO_PERMS).toggleRead)}
                            onClick={() =>
                              isUnread ? onMarkRead(openId) : onMarkUnread(openId)
                            }
                            className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-lg:hidden"
                          >
                            {isUnread ? <Mail className="h-4 w-4" /> : <MailOpen className="h-4 w-4" />}
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {readToggleLabel(buildMessageMenu({ ...item, isUnread }, NO_PERMS).toggleRead)}
                        </TooltipContent>
                      </Tooltip>
                      {(["flag", "pin"] as const).map((kind) => {
                        const menuModel = buildMessageMenu({ ...item, isUnread }, NO_PERMS);
                        const action = kind === "flag" ? menuModel.toggleFlag : menuModel.togglePin;
                        const on = kind === "flag" ? item.is_flagged : item.is_pinned;
                        const label = { flag: "Flag", unflag: "Unflag", pin: "Pin", unpin: "Unpin" }[action];
                        const Icon = kind === "flag" ? Flag : Pin;
                        return (
                          <Tooltip key={kind}>
                            <TooltipTrigger asChild>
                              <button
                                type="button"
                                aria-label={label}
                                aria-pressed={Boolean(on)}
                                onClick={() => void bulk?.markMessage(openId, action)}
                                className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring max-lg:hidden"
                              >
                                <Icon
                                  className={cn(
                                    "h-4 w-4",
                                    on && (kind === "flag" ? "fill-destructive text-destructive" : "fill-primary text-primary")
                                  )}
                                />
                              </button>
                            </TooltipTrigger>
                            <TooltipContent>{label}</TooltipContent>
                          </Tooltip>
                        );
                      })}
                      <MessageActionsMenu
                        item={item}
                        isUnread={isUnread}
                        folders={folders}
                        onMessageAction={onMessageAction}
                        onMarkRead={onMarkRead}
                        onMarkUnread={onMarkUnread}
                        onAssignFolder={onAssignFolder}
                        onOpenChange={(open) => setMenuOpenId(open ? openId : null)}
                      />
                        </>
                      )}
                    </div>
                  )}
                  {selectable && (
                    <div
                      className={cn(
                        // left-11 (44px) lines up with the avatar, which
                        // now sits to the right of the ▶/▼ toggle column
                        // (px-4 row padding + the toggle's w-6 + gap-1).
                        "absolute left-11 top-3 z-[2] flex h-9 w-9 items-center justify-center rounded-full bg-background transition-opacity focus-within:opacity-100",
                        isChecked || selectionActive ? "opacity-100" : "opacity-0 group-hover/row:opacity-100"
                      )}
                    >
                      <Checkbox
                        checked={isChecked}
                        onCheckedChange={() => bulk!.toggle(openId)}
                        aria-label={isChecked ? "Deselect message" : "Select message"}
                      />
                    </div>
                  )}
                </>
              );

              const messageRow = !canContextMenu ? (
                <li className="group/row relative">{rowContent}</li>
              ) : (
                <ContextMenu>
                  <ContextMenuTrigger asChild>
                    <li
                      className="group/row relative"
                      onContextMenu={() => {
                        // Right-click on a selected row keeps the whole
                        // selection (bulk menu); on an unselected row it
                        // replaces the selection with just that row.
                        const target = resolveContextTarget(bulk!.selectedIds, openId);
                        if (target.selection !== bulk!.selectedIds) bulk!.setSelection(target.selection);
                      }}
                    >
                      {rowContent}
                    </li>
                  </ContextMenuTrigger>
                  <MessageContextMenuContent
                    item={item}
                    isUnread={isUnread}
                    folders={folders!}
                    selectedRows={bulk!.selectedIds.has(openId) ? selectedRows : [toActionRow(item)]}
                    onMessageAction={onMessageAction!}
                    onMarkRead={onMarkRead!}
                    onMarkUnread={onMarkUnread!}
                    onAssignFolder={onAssignFolder!}
                  />
                </ContextMenu>
              );

              return (
                <Fragment key={item.interaction_id}>
                  {messageRow}
                  {hasThread && isThreadExpanded && (
                    <li className="bg-muted/10 py-1">
                      {threadEntry === "loading" && (
                        <div className="px-10 py-2">
                          <WorkflowLoader loading size={18} />
                        </div>
                      )}
                      {threadEntry === "error" && (
                        <p className="px-10 py-2 text-[11.5px] text-destructive">
                          Couldn&apos;t load messages.
                        </p>
                      )}
                      {Array.isArray(threadEntry) &&
                        threadEntry.map((message) => {
                          const isMessageSelected = selectedMessageId === message.interaction_id;
                          return (
                            <button
                              type="button"
                              key={message.interaction_id}
                              onClick={() => onOpenMessage?.(openId, message.interaction_id)}
                              className={cn(
                                "block w-full border-l-2 py-1.5 pl-3 ml-10 mr-4 text-left transition-colors hover:bg-muted/40",
                                isMessageSelected ? "border-primary bg-primary/5" : "border-border"
                              )}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-[12px] font-medium text-foreground/80">
                                  {messageSender(message) ?? "System"}
                                </span>
                                <span className="flex flex-none items-center gap-1 text-[11px] text-muted-foreground">
                                  {message.attachments && message.attachments.length > 0 && (
                                    <Paperclip className="h-3 w-3" aria-label="Has attachment" />
                                  )}
                                  {formatRelativeTime(message.created_at)}
                                </span>
                              </div>
                              <p className="mt-0.5 truncate text-[11.5px] text-foreground/70">
                                {message.subject || subject}
                              </p>
                              <p className="truncate text-[12px] text-muted-foreground">
                                {summarize(message)}
                              </p>
                            </button>
                          );
                        })}
                    </li>
                  )}
                </Fragment>
              );
            })}
          </ul>
          </TooltipProvider>
        )}
      </div>

      {filtered.length > 0 && (
        <div className="flex flex-col gap-1.5 border-t border-border px-4 py-2.5">
          <p className="text-[11.5px] text-muted-foreground">
            Showing {pageStartIndex + 1}–{pageEndIndex} of {filtered.length}
            {hasMore ? "+" : ""} message{filtered.length === 1 ? "" : "s"}
          </p>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <span className="whitespace-nowrap">Messages per page:</span>
              <Select
                value={String(pageSize)}
                onValueChange={(v) => setPersistedPageSize(Number(v))}
                disabled={isLoadingNextBatch || isJumpingToLast}
              >
                <SelectTrigger className="h-7 w-[76px] text-[11.5px]" aria-label="Messages per page">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <SelectItem key={size} value={String(size)}>
                      {size}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={page === 1 || isLoadingNextBatch || isJumpingToLast}
                onClick={goToFirstPage}
                aria-label="First page"
              >
                <ChevronsLeft className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={page === 1 || isLoadingNextBatch || isJumpingToLast}
                onClick={goToPreviousPage}
                aria-label="Previous page"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <span className="whitespace-nowrap px-1.5 text-[11.5px] text-muted-foreground">
                Page {page} of {totalPagesKnown}
                {hasMore ? "+" : ""}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={(isOnLastKnownPage && !hasMore) || isLoadingNextBatch || isJumpingToLast}
                onClick={goToNextPage}
                aria-label="Next page"
              >
                <ChevronRight className={cn("h-3.5 w-3.5", isLoadingNextBatch && "animate-pulse")} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                disabled={(isOnLastKnownPage && !hasMore) || isLoadingNextBatch || isJumpingToLast}
                onClick={goToLastPage}
                aria-label="Last page"
              >
                <ChevronsRight className={cn("h-3.5 w-3.5", isJumpingToLast && "animate-pulse")} />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
