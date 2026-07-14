"use client";

import { useMemo, useState } from "react";
import { Bell, RefreshCw, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/utils";
import type { NotificationItem } from "@tw/types";

// Same visual language as MessageList (card shell, sticky header,
// divided row list) but not the same component — a NotificationItem
// has no client/priority/attachment/status vocabulary to filter by,
// so this only supports search + unread-only + refresh, not the full
// Filters dropdown MessageList has.

interface SystemMailListProps {
  items: NotificationItem[];
  isLoading: boolean;
  onOpen: (notification: NotificationItem) => void;
  onRefresh: () => void;
}

function typeLabel(notificationType: string): string {
  if (notificationType.startsWith("ESCALATION_")) return "Escalation";
  if (notificationType.startsWith("SLA_")) return "SLA";
  return "System";
}

export function SystemMailList({ items, isLoading, onOpen, onRefresh }: SystemMailListProps) {
  const [search, setSearch] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return items
      .filter((item) => !unreadOnly || !item.is_read)
      .filter(
        (item) =>
          !term ||
          item.title.toLowerCase().includes(term) ||
          item.message.toLowerCase().includes(term)
      )
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  }, [items, search, unreadOnly]);

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card lg:h-[calc(100vh-7rem)]">
      <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-card px-4 py-3.5">
        <div className="min-w-0">
          <h2 className="truncate text-[15px] font-semibold text-foreground">System</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onRefresh} aria-label="Refresh" className="h-8 w-8">
          <RefreshCw className={cn("h-4 w-4", isLoading && "animate-spin")} />
        </Button>
      </div>

      <div className="sticky top-[57px] z-10 flex flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-2.5">
        <div className="relative min-w-[180px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search subject or message..."
            className="h-9 pl-8 text-[13px]"
          />
        </div>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Checkbox checked={unreadOnly} onCheckedChange={(v) => setUnreadOnly(Boolean(v))} />
          Unread only
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && filtered.length === 0 ? (
          <div className="flex flex-col gap-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-full min-h-[24rem] flex-col items-center justify-center gap-4 p-8 text-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
              <Bell className="h-8 w-8 text-muted-foreground" />
            </div>
            <div>
              <p className="text-base font-semibold text-foreground">No system notices</p>
              <p className="mt-1 text-sm text-muted-foreground">
                SLA breach and escalation notices will show up here.
              </p>
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {filtered.map((item) => (
              <li key={item.notification_id}>
                <button
                  type="button"
                  onClick={() => onOpen(item)}
                  className={cn(
                    "group flex w-full items-start gap-3 px-4 py-3 text-left transition-all duration-150 hover:z-[1] hover:-translate-y-0.5 hover:bg-muted/60 hover:shadow-sm",
                    !item.is_read && "bg-primary/[0.03]"
                  )}
                >
                  <div className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-primary/10 text-primary">
                    <Bell className="h-4 w-4" />
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {!item.is_read && (
                        <span className="h-1.5 w-1.5 flex-none rounded-full bg-primary" aria-label="Unread" />
                      )}
                      <span
                        className={cn(
                          "truncate text-[13.5px]",
                          !item.is_read ? "font-semibold text-foreground" : "font-medium text-foreground/90"
                        )}
                      >
                        System
                      </span>
                      <span className="ml-auto flex-none whitespace-nowrap text-[11px] text-muted-foreground">
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </div>
                    <p
                      className={cn(
                        "mt-0.5 truncate text-[13px]",
                        !item.is_read ? "font-medium text-foreground" : "text-muted-foreground"
                      )}
                    >
                      {item.title}
                    </p>
                    <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{item.message}</p>
                  </div>

                  <div className="flex flex-none flex-col items-end gap-1.5 pl-1">
                    <Badge variant="secondary" className="text-[10px]">
                      {typeLabel(item.notification_type)}
                    </Badge>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {filtered.length > 0 && (
        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5">
          <p className="text-[11.5px] text-muted-foreground">
            {filtered.length} notice{filtered.length === 1 ? "" : "s"}
          </p>
        </div>
      )}
    </div>
  );
}
