"use client";

import { memo, type ReactNode } from "react";
import {
  Archive,
  Bell,
  FileEdit,
  Inbox as InboxIcon,
  Pencil,
  Reply,
  Send,
  Ticket as TicketIcon,
  UserCheck,
  UserX,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { MailViewKey } from "@tw/hooks/useMailInbox";

// Exact order required by the Mail spec: Compose, Inbox, Unassigned,
// My Claims, Sent, Drafts, Replied, Ticketed, Archived.
// Compose is rendered separately above this list (it's an action,
// not a folder view).
const VIEW_ITEMS: Array<{ key: MailViewKey; label: string; icon: LucideIcon }> = [
  { key: "pending", label: "Inbox", icon: InboxIcon },
  { key: "unassigned", label: "Unassigned", icon: UserX },
  { key: "mine", label: "My Claims", icon: UserCheck },
  { key: "sent", label: "Sent", icon: Send },
  { key: "drafts", label: "Drafts", icon: FileEdit },
  { key: "replied", label: "Replied", icon: Reply },
  { key: "ticketed", label: "Ticketed", icon: TicketIcon },
  { key: "archived", label: "Archived", icon: Archive },
  // Internal system notices (SLA breach ladder + escalation workflow)
  // rendered in mail format — see useMailInbox.ts's systemNotifications
  // and SystemMailList/SystemMailDetailsView. Not part of the Mail
  // spec's original required order above; appended rather than
  // inserted so that order stays intact.
  { key: "system", label: "System", icon: Bell },
];

interface MailSidebarProps {
  activeView: MailViewKey;
  isComposing: boolean;
  onSelectView: (view: MailViewKey) => void;
  onCompose: () => void;
  counts: Partial<Record<MailViewKey, number>>;
  isSupervisor: boolean;
}

function CountBadge({ count }: { count: number }): ReactNode {
  if (!count) return null;
  return (
    <span className="ml-auto min-w-[1.375rem] rounded-full bg-muted px-1.5 py-0.5 text-center text-[11px] font-semibold tabular-nums text-muted-foreground group-data-[active=true]:bg-primary/15 group-data-[active=true]:text-primary">
      {count > 99 ? "99+" : count}
    </span>
  );
}

// Memoized: InboxPage re-renders on every Mail search keystroke (the
// search box's state lives in the same hook this sidebar reads its
// props from), and this sidebar's own content — nav items — has
// nothing to do with the search text. Only actually skips re-rendering
// if its props are referentially stable; see useMailInbox's
// setActiveView (useCallback-wrapped) and InboxPage's own
// useCallback-wrapped handlers passed in below.
export const MailSidebar = memo(function MailSidebar({
  activeView,
  isComposing,
  onSelectView,
  onCompose,
  counts,
  isSupervisor,
}: MailSidebarProps) {
  return (
    <aside className="flex w-full flex-col gap-4 overflow-y-auto rounded-xl border border-border bg-card p-3 shadow-card lg:sticky lg:top-0 lg:h-[calc(100vh-7rem)] lg:w-[248px] lg:flex-none">
      <Button
        onClick={onCompose}
        data-active={isComposing}
        size="sm"
        className="h-9 w-fit self-start gap-2 rounded-lg px-4 text-[13px] font-semibold shadow-sm"
      >
        <Pencil className="h-3.5 w-3.5" />
        Compose
      </Button>

      <nav className="flex flex-col gap-0.5">
        {VIEW_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = !isComposing && activeView === item.key;
          return (
            <button
              key={item.key}
              type="button"
              data-active={isActive}
              onClick={() => onSelectView(item.key)}
              className={cn(
                "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-all duration-150",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-foreground/80 hover:translate-x-0.5 hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className={cn("h-4 w-4 flex-none", isActive ? "text-primary" : "text-muted-foreground")} />
              <span className="truncate">{item.label}</span>
              <CountBadge count={counts[item.key] ?? 0} />
            </button>
          );
        })}
      </nav>

      {isSupervisor && (
        <button
          type="button"
          data-active={!isComposing && activeView === "all"}
          onClick={() => onSelectView("all")}
          className={cn(
            "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-all duration-150",
            !isComposing && activeView === "all"
              ? "bg-primary/10 text-primary"
              : "text-foreground/80 hover:translate-x-0.5 hover:bg-muted hover:text-foreground"
          )}
        >
          <InboxIcon className="h-4 w-4 flex-none text-muted-foreground" />
          <span className="truncate">All Inboxes</span>
          <CountBadge count={counts.all ?? 0} />
        </button>
      )}
    </aside>
  );
});
