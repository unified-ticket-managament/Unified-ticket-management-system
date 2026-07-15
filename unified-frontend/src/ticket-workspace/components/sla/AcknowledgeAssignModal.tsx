"use client";

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

// Shared by SlaCard.tsx and TicketsListPage.tsx — see
// useAcknowledgeAndAssign.ts for why acknowledging an escalation
// always also requires picking who owns the ticket going forward.
// `groups` is role-scoped server-side (see EscalationService.
// get_acknowledge_candidates) — who else appears here differs by the
// caller's own role, rendered as one <optgroup> per role.
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
      title="Acknowledge & Assign"
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          size="sm"
          isLoading={isSubmitting}
          disabled={!selectedAgentId}
          onClick={onConfirm}
        >
          Confirm
        </Button>
      }
    >
      <p className="mb-3 text-xs text-muted">
        Acknowledging this escalation requires deciding who owns it going forward — yourself, or
        another agent.
      </p>
      <SelectInput
        label="Assign to"
        value={selectedAgentId}
        onChange={(e) => onSelectAgent(e.target.value)}
      >
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
