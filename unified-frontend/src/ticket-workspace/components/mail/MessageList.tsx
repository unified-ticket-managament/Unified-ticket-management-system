"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Paperclip,
  RefreshCw,
  Search,
  SlidersHorizontal,
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
import type { CategoryResponse, ClientResponse, InboxItem, SLAPolicyResponse, TicketPriority } from "@tw/types";
import { MailEmptyState } from "@tw/components/mail/MailEmptyState";
import { listSlaPolicies } from "@tw/api/sla";
import {
  classifyTier,
  computeElapsedFraction,
  computeFirstResponseDueAt,
  SLA_TIER_LABEL,
  type SlaTier,
} from "@tw/lib/slaMath";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import { mergedClientFilterOptions } from "@tw/lib/clientFilter";

type SortKey = "newest" | "oldest" | "sender";
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
}

export function MessageList({
  folderLabel,
  items,
  isLoading,
  isError = false,
  variant = "standalone",
  selectedId = null,
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
  onOpenFullScreen,
  onCompose,
  onRefresh,
  hasMore,
  onLoadMore,
}: MessageListProps) {
  const [sort, setSort] = useState<SortKey>("newest");
  // Unread/attachments have no backend filter equivalent (unread
  // isn't queryable server-side yet — see InboxItemResponse.is_read's
  // own docstring — and has_attachments is a per-row derived flag,
  // not a real column) — these stay client-side, over whatever page
  // is currently loaded, same as before.
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [attachmentsOnly, setAttachmentsOnly] = useState(false);
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
    if (slaRiskFilter !== "ALL") {
      rows = rows.filter((item) => firstResponseTierFor(item) === slaRiskFilter);
    }

    return [...rows].sort((a, b) => {
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
  }, [items, unreadOnly, attachmentsOnly, sort, openedIds, slaRiskFilter, targetMinutes, now]);

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
  }, [pageSize, items, unreadOnly, attachmentsOnly, sort, slaRiskFilter]);

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

            {activeFilterCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  onPriorityFilterChange("ALL");
                  onCategoryFilterChange("ALL");
                  setUnreadOnly(false);
                  setAttachmentsOnly(false);
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
              const displayName = isCategoryInbox ? item.category_name || "Category" : item.client_name;

              return (
                <li key={item.interaction_id}>
                  <button
                    type="button"
                    onClick={() => {
                      // Already open in the reading pane — re-firing
                      // onOpen would just re-run "open thread" (and
                      // its mark-read side effect) for no reason; use
                      // the dedicated Refresh action for that instead.
                      if (isSelected) return;
                      onOpen(openId);
                    }}
                    onDoubleClick={() => onOpenFullScreen?.(openId)}
                    disabled={isOpening}
                    className={cn(
                      "group flex w-full items-start gap-3 px-4 py-3 text-left transition-all duration-150 hover:z-[1] hover:-translate-y-0.5 hover:bg-muted/60 hover:shadow-sm",
                      isUnread && "bg-primary/[0.03]",
                      isSelected && "bg-primary/10 hover:bg-primary/10",
                      isOpening && "opacity-60"
                    )}
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
                            isUnread ? "font-semibold text-foreground" : "font-medium text-foreground/90"
                          )}
                        >
                          {displayName}
                        </span>
                        {isCategoryInbox && (
                          <span className="flex-none rounded border border-border px-1 py-px text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                            Category
                          </span>
                        )}
                        {item.has_attachments && <Paperclip className="h-3 w-3 flex-none text-muted-foreground" />}
                        <span className="ml-auto flex-none whitespace-nowrap text-[11px] text-muted-foreground">
                          {formatRelativeTime(item.latest_at ?? item.received_at)}
                        </span>
                      </div>
                      <p
                        className={cn(
                          "mt-0.5 truncate text-[13px]",
                          isUnread ? "font-medium text-foreground" : "text-muted-foreground"
                        )}
                      >
                        {item.subject}
                      </p>
                      {preview && (
                        <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{preview}</p>
                      )}
                    </div>

                    <div className="flex flex-none flex-col items-end gap-1.5 pl-1">
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
                </li>
              );
            })}
          </ul>
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
