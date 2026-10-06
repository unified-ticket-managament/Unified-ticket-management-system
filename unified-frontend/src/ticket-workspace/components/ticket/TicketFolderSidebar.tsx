import { memo, type ReactNode } from "react";
import { Inbox, ListTree, ShieldAlert, UserCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PoolTab } from "@tw/context/WorkflowContext";
import type { TicketViewCounts } from "@tw/api/ticket";

// Outlook-style left nav for the Tickets workspace — visual language
// borrowed from MailSidebar.tsx (nav rows + count badges), but every
// item maps to one of the four real, already-server-backed ticket
// views (view=pool|mine|all|escalated, same as the old TicketsListPage
// table's own tabs) rather than an invented Mail-style folder system.
// "Focused"/"Other" are presentation-only section headers grouping
// those same four views — not a fifth merged data view — per the
// approved redesign plan.
interface TicketFolderSidebarProps {
  activeView: PoolTab;
  onSelectView: (view: PoolTab) => void;
  counts: TicketViewCounts;
  canSeePoolTab: boolean;
  canSeeMineTab: boolean;
  canSeeAllTab: boolean;
  canSeeEscalatedTab: boolean;
  variant?: "standalone" | "panel";
}

function CountBadge({ count }: { count: number }): ReactNode {
  if (!count) return null;
  return (
    <span className="ml-auto min-w-[1.375rem] rounded-full bg-muted px-1.5 py-0.5 text-center text-[11px] font-semibold tabular-nums text-muted-foreground group-data-[active=true]:bg-primary/15 group-data-[active=true]:text-primary">
      {count > 99 ? "99+" : count}
    </span>
  );
}

function NavRow({
  isActive,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  isActive: boolean;
  onClick: () => void;
  icon: typeof Inbox;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      data-active={isActive}
      onClick={onClick}
      className={cn(
        "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-all duration-150",
        isActive
          ? "bg-primary/10 text-primary"
          : "text-foreground/80 hover:translate-x-0.5 hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon className={cn("h-4 w-4 flex-none", isActive ? "text-primary" : "text-muted-foreground")} />
      <span className="truncate">{label}</span>
      <CountBadge count={count} />
    </button>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </p>
  );
}

export const TicketFolderSidebar = memo(function TicketFolderSidebar({
  activeView,
  onSelectView,
  counts,
  canSeePoolTab,
  canSeeMineTab,
  canSeeAllTab,
  canSeeEscalatedTab,
  variant = "standalone",
}: TicketFolderSidebarProps) {
  return (
    <aside
      className={cn(
        "flex flex-col gap-4 overflow-y-auto p-3",
        variant === "panel"
          ? "h-full w-full"
          : "w-full rounded-xl border border-border bg-card shadow-card lg:sticky lg:top-0 lg:h-[calc(100vh-7rem)] lg:w-[248px] lg:flex-none"
      )}
    >
      {(canSeeMineTab || canSeePoolTab) && (
        <div className="flex flex-col gap-0.5">
          <SectionLabel>Focused</SectionLabel>
          {canSeeMineTab && (
            <NavRow
              isActive={activeView === "mine"}
              onClick={() => onSelectView("mine")}
              icon={UserCheck}
              label="My Tickets"
              count={counts.mine}
            />
          )}
          {canSeePoolTab && (
            <NavRow
              isActive={activeView === "pool"}
              onClick={() => onSelectView("pool")}
              icon={Inbox}
              label="Open Pool"
              count={counts.pool}
            />
          )}
        </div>
      )}

      {canSeeAllTab && (
        <div className="flex flex-col gap-0.5 border-t border-border pt-3">
          <SectionLabel>Other</SectionLabel>
          <NavRow
            isActive={activeView === "all"}
            onClick={() => onSelectView("all")}
            icon={ListTree}
            label="All Tickets"
            count={counts.all}
          />
        </div>
      )}

      {canSeeEscalatedTab && (
        <div className="flex flex-col gap-0.5 border-t border-border pt-3">
          <NavRow
            isActive={activeView === "escalated"}
            onClick={() => onSelectView("escalated")}
            icon={ShieldAlert}
            label="Escalated"
            count={counts.escalated}
          />
        </div>
      )}
    </aside>
  );
});
