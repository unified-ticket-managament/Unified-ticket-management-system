import { FolderInput, UserPlus } from "lucide-react";
import { Button } from "@tw/components/common/Button";

// Outlook-style top ribbon for the Tickets workspace. Deliberately
// minimal — only buttons backed by a real, already-existing UTMS
// action are shown (see the approved redesign plan): Assign (the
// existing AssignmentService-backed transfer/claim flow, TicketActions.tsx)
// and Categorize (the existing PATCH /tickets/{id} ticket_type field,
// gated by ticket:change_category). Delete/Archive/Rules/Mark as
// Read-Unread/Follow-up/Forward/New Ticket are intentionally absent —
// none of them map to a real, distinct ticket action today, and none
// get a new backend field/endpoint just to imitate Outlook.
interface TicketRibbonProps {
  selectedCount: number;
  canAssign: boolean;
  canCategorize: boolean;
  onAssign: () => void;
  onCategorize: () => void;
}

export function TicketRibbon({
  selectedCount,
  canAssign,
  canCategorize,
  onAssign,
  onCategorize,
}: TicketRibbonProps) {
  const hasSelection = selectedCount > 0;

  return (
    <div className="flex flex-none items-center gap-2 border-b border-border bg-surface px-3 py-2">
      <Button
        variant="secondary"
        size="sm"
        disabled={!hasSelection || !canAssign}
        title={!canAssign ? "Requires the Assign/Transfer permission" : undefined}
        onClick={onAssign}
      >
        <UserPlus size={14} />
        Assign
      </Button>
      <Button
        variant="secondary"
        size="sm"
        disabled={!hasSelection || !canCategorize}
        title={!canCategorize ? "Requires the Change Category permission" : undefined}
        onClick={onCategorize}
      >
        <FolderInput size={14} />
        Categorize
      </Button>
      {hasSelection && (
        <span className="ml-1 text-[12px] font-medium text-muted">
          {selectedCount} selected
        </span>
      )}
    </div>
  );
}
