import { History, ListChecks, MessageSquareText, Paperclip, Send } from "lucide-react";
import { TicketTimeline } from "@tw/components/ticket/TicketTimeline";
import { TicketAuditLog } from "@tw/components/ticket/TicketAuditLog";
import { TicketComposer } from "@tw/components/ticket/TicketComposer";
import { TicketAttachmentsTab } from "@tw/components/ticket/TicketAttachmentsTab";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

// Mirrors TicketActions.tsx's own isFrozenByEscalation — an actively
// (not yet acknowledged) escalated ticket is frozen for its currently-
// assigned agent, everywhere an action lives, not just the top-right
// action row. Supervisors are exempt (acknowledging/assigning is how
// they're meant to interact with it).
const SUPERVISOR_ROLES = new Set(["Team Lead", "Account Manager", "Site Lead", "Super Admin"]);

export type ActivityTab = "timeline" | "audit" | "reply" | "note" | "attachments";

interface TicketActivityPanelProps {
  activeTab: ActivityTab;
  onTabChange: (tab: ActivityTab) => void;
  onTimelineChanged: () => void;
  auditRefreshToken?: number;
}

const TABS: Array<{ key: ActivityTab; label: string; icon: typeof History }> = [
  { key: "timeline", label: "Timeline", icon: History },
  { key: "audit", label: "Audit Log", icon: ListChecks },
  { key: "reply", label: "Reply", icon: Send },
  { key: "note", label: "Internal Note", icon: MessageSquareText },
  { key: "attachments", label: "Attachments", icon: Paperclip },
];

// Timeline, Audit Log, Reply, and Internal Note all live as tabs of
// one panel — Reply/Internal Note used to be opened via separate
// "Actions" tiles below the fold; putting them alongside Timeline/
// Audit Log keeps every ticket activity one click away from the same
// row instead of scattered across the page.
export function TicketActivityPanel({
  activeTab,
  onTabChange,
  onTimelineChanged,
  auditRefreshToken,
}: TicketActivityPanelProps) {
  const { currentUser } = useAuthContext();
  const { activeTicket } = useWorkflowContext();
  const isSupervisor = !!currentUser && SUPERVISOR_ROLES.has(currentUser.role);
  const isFrozenByEscalation =
    !isSupervisor &&
    !!activeTicket?.is_escalated &&
    activeTicket.escalation_status === "ACTIVE";

  return (
    <div className="rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex flex-wrap items-center gap-1 border-b border-border px-5 pt-3">
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

      {activeTab === "timeline" && <TicketTimeline onChanged={onTimelineChanged} flat />}
      {activeTab === "audit" && <TicketAuditLog refreshToken={auditRefreshToken} flat />}
      {activeTab === "attachments" && (
        <TicketAttachmentsTab onChanged={onTimelineChanged} flat />
      )}
      {(activeTab === "reply" || activeTab === "note") &&
        (isFrozenByEscalation ? (
          <p className="px-5 py-6 text-sm text-muted">
            This ticket has been escalated and is awaiting acknowledgment — it
            cannot be worked until a supervisor acknowledges and reassigns it.
          </p>
        ) : (
          <TicketComposer
            key={activeTab}
            mode={activeTab === "reply" ? "reply" : "note"}
            lockMode
            flat
            onClose={() => onTabChange("timeline")}
            onSent={() => {
              onTimelineChanged();
              onTabChange("timeline");
            }}
          />
        ))}
    </div>
  );
}
