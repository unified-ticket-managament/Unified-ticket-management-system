"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
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
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { TIME_FILTERS, type TimeFilterKey } from "@tw/hooks/useMailInbox";
import { formatRelativeTime } from "@/lib/utils";
import type { ClientResponse, InboxItem, TicketPriority } from "@tw/types";
import { MailEmptyState } from "@tw/components/mail/MailEmptyState";

type SortKey = "newest" | "oldest" | "sender";
type PriorityFilter = "ALL" | TicketPriority;

const PAGE_SIZE = 10;

const STATUS_META: Record<string, { label: string; variant: "warning" | "success" | "secondary" }> = {
  PENDING: { label: "Pending", variant: "warning" },
  ASSIGNED: { label: "Replied", variant: "success" },
  IGNORED: { label: "Archived", variant: "secondary" },
};

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
};

function statusMeta(item: InboxItem): { label: string; variant: "warning" | "success" | "secondary" | "default" } {
  if (item.ticket_id) return { label: "Ticketed", variant: "default" };
  return STATUS_META[item.status] ?? { label: item.status, variant: "secondary" };
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
  openingId: string | null;
  openedIds: Set<string>;
  search: string;
  onSearchChange: (value: string) => void;
  timeFilter: TimeFilterKey;
  onTimeFilterChange: (value: TimeFilterKey) => void;
  clientFilter: string;
  onClientFilterChange: (value: string) => void;
  clients: ClientResponse[];
  onOpen: (interactionId: string) => void;
  onCompose: () => void;
  onRefresh: () => void;
}

export function MessageList({
  folderLabel,
  items,
  isLoading,
  openingId,
  openedIds,
  search,
  onSearchChange,
  timeFilter,
  onTimeFilterChange,
  clientFilter,
  onClientFilterChange,
  clients,
  onOpen,
  onCompose,
  onRefresh,
}: MessageListProps) {
  const [sort, setSort] = useState<SortKey>("newest");
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>("ALL");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [attachmentsOnly, setAttachmentsOnly] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [page, setPage] = useState(0);

  const categories = useMemo(() => {
    const set = new Set<string>();
    items.forEach((item) => {
      if (item.ticket_category) set.add(item.ticket_category);
    });
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    let rows = items;
    if (priorityFilter !== "ALL") rows = rows.filter((item) => item.ticket_priority === priorityFilter);
    if (unreadOnly) rows = rows.filter((item) => !openedIds.has(item.open_interaction_id ?? item.interaction_id));
    if (attachmentsOnly) rows = rows.filter((item) => item.has_attachments);
    if (categoryFilter !== "ALL") rows = rows.filter((item) => item.ticket_category === categoryFilter);

    return [...rows].sort((a, b) => {
      if (sort === "sender") return a.client_name.localeCompare(b.client_name);
      const aTime = new Date(a.latest_at ?? a.received_at).getTime();
      const bTime = new Date(b.latest_at ?? b.received_at).getTime();
      return sort === "oldest" ? aTime - bTime : bTime - aTime;
    });
  }, [items, priorityFilter, unreadOnly, attachmentsOnly, categoryFilter, sort, openedIds]);

  useEffect(() => {
    setPage(0);
  }, [search, priorityFilter, unreadOnly, attachmentsOnly, categoryFilter, sort, timeFilter, clientFilter, folderLabel]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const clampedPage = Math.min(page, totalPages - 1);
  const paged = filtered.slice(clampedPage * PAGE_SIZE, clampedPage * PAGE_SIZE + PAGE_SIZE);

  const activeFilterCount = [
    priorityFilter !== "ALL",
    unreadOnly,
    attachmentsOnly,
    categoryFilter !== "ALL",
    timeFilter !== "ALL",
  ].filter(Boolean).length;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card">
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
            {clients.map((client) => (
              <SelectItem key={client.client_id} value={client.client_id}>
                {client.name}
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
            <Select value={priorityFilter} onValueChange={(v) => setPriorityFilter(v as PriorityFilter)}>
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
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="mt-1.5 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Any category</SelectItem>
                {categories.map((category) => (
                  <SelectItem key={category} value={category}>
                    {category}
                  </SelectItem>
                ))}
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
                  setPriorityFilter("ALL");
                  setCategoryFilter("ALL");
                  setUnreadOnly(false);
                  setAttachmentsOnly(false);
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

      <div className="flex-1 overflow-y-auto">
        {isLoading && paged.length === 0 ? (
          <div className="flex flex-col gap-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4">
            <MailEmptyState onCompose={onCompose} />
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {paged.map((item) => {
              const openId = item.open_interaction_id ?? item.interaction_id;
              const isUnread = !openedIds.has(openId);
              const status = statusMeta(item);
              const isOpening = openingId === openId;

              return (
                <li key={item.interaction_id}>
                  <button
                    type="button"
                    onClick={() => onOpen(openId)}
                    disabled={isOpening}
                    className={cn(
                      "group flex w-full items-start gap-3 px-4 py-3 text-left transition-all duration-150 hover:z-[1] hover:-translate-y-0.5 hover:bg-muted/60 hover:shadow-sm",
                      isUnread && "bg-primary/[0.03]",
                      isOpening && "opacity-60"
                    )}
                  >
                    <div className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-primary/10 text-[12px] font-semibold text-primary">
                      {initialsOf(item.client_name)}
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
                          {item.client_name}
                        </span>
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
                      <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
                        {item.latest_message ?? "No preview available."}
                      </p>
                    </div>

                    <div className="flex flex-none flex-col items-end gap-1.5 pl-1">
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
        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5">
          <p className="text-[11.5px] text-muted-foreground">
            {filtered.length} message{filtered.length === 1 ? "" : "s"} · Page {clampedPage + 1} of {totalPages}
          </p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              disabled={clampedPage === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              disabled={clampedPage >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
