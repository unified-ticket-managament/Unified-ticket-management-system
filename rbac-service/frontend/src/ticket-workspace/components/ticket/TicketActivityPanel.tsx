import { History, ListChecks } from "lucide-react";
import { TicketTimeline } from "@tw/components/ticket/TicketTimeline";
import { TicketAuditLog } from "@tw/components/ticket/TicketAuditLog";

export type ActivityTab = "timeline" | "audit";

interface TicketActivityPanelProps {
  activeTab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  onTimelineChanged: () => void;
  auditRefreshToken?: number;
}

const TABS: Array<{ key: ActivityTab; label: string; icon: typeof History }> = [
  { key: "timeline", label: "Timeline", icon: History },
  { key: "audit", label: "Audit Log", icon: ListChecks },
];

// Timeline and Audit Log used to be two separate stacked cards (the
// audit trail buried at the bottom of the right sidebar, below
// Actions) — pulling the audit trail into a tab right next to the
// Timeline keeps both one click away without the page just being a
// tall stack of boxes.
export function TicketActivityPanel({
  activeTab,
  onTabChange,
  onTimelineChanged,
  auditRefreshToken,
}: TicketActivityPanelProps) {
  return (
    <div className="rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center gap-1 border-b border-border px-5 pt-3">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.key;
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => onTabChange(tab.key)}
              aria-pressed={isActive}
              className={`flex items-center gap-1.5 border-b-2 px-3 pb-2.5 text-[13px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                isActive
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-slate-700"
              }`}
            >
              <Icon size={14} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === "timeline" ? (
        <TicketTimeline onChanged={onTimelineChanged} flat />
      ) : (
        <TicketAuditLog refreshToken={auditRefreshToken} flat />
      )}
    </div>
  );
}
