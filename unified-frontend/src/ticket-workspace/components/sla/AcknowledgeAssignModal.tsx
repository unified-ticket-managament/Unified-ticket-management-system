"use client";

import { AlertCircle } from "lucide-react";
import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput } from "@tw/components/common/FormField";
import type { AssignableGroup, AssignableUserSummary } from "@tw/types";

interface AcknowledgeAssignModalProps {
  open: boolean;
  onClose: () => void;
  me: AssignableUserSummary | null;
  groups: AssignableGroup[];
  selectedAgentId: string;
  onSelectAgent: (agentId: string) => void;
  onConfirm: () => void;
  isSubmitting: boolean;
}

// Shared by SlaCard.tsx and TicketsListPage.tsx. A single form, not
// two sequential steps: acknowledging an escalation and assigning the
// ticket now happen as one atomic backend call (see
// useAcknowledgeAndAssign.ts and InteractionService.
// acknowledge_and_assign_escalation), so there's no longer an
// intermediate "acknowledged, now pick an assignee" state to render.
// The submit button stays disabled until an assignee is chosen —
// mirroring the backend's own required assignee_id — but that's a UX
// guard only, not the real enforcement. `groups` is role-scoped
// server-side (see EscalationService.get_acknowledge_candidates) —
// who else appears here differs by the caller's own role, rendered as
// one <optgroup> per role.
export function AcknowledgeAssignModal({
  open,
  onClose,
  me,
  groups,
  selectedAgentId,
  onSelectAgent,
  onConfirm,
  isSubmitting,
}: AcknowledgeAssignModalProps) {
  return (
    <Modal
      open={open}
      title="Acknowledge & Assign Escalation"
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          size="sm"
          isLoading={isSubmitting}
          disabled={!selectedAgentId}
          onClick={onConfirm}
        >
          Acknowledge &amp; Assign
        </Button>
      }
    >
      <p className="mb-3 flex items-start gap-1.5 text-xs text-muted">
        <AlertCircle size={13} className="mt-0.5 flex-none" />
        This ticket has escalated to you and is awaiting acknowledgment. Choose who should own it
        going forward — acknowledging and assigning happen together, so an assignee is required.
      </p>
      <SelectInput
        label="Assign to"
        value={selectedAgentId}
        onChange={(e) => onSelectAgent(e.target.value)}
      >
        <option value="" disabled>
          Select an assignee…
        </option>
        {me && <option value={me.user_id}>{`Myself (${me.name})`}</option>}
        {groups.map((group) => (
          <optgroup key={group.role} label={group.role}>
            {group.users.map((user) => (
              <option key={user.user_id} value={user.user_id}>
                {user.name}
              </option>
            ))}
          </optgroup>
        ))}
      </SelectInput>
    </Modal>
  );
}
