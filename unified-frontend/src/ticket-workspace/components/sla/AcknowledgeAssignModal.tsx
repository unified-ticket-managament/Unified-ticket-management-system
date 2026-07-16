"use client";

import { CheckCircle2 } from "lucide-react";
import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput } from "@tw/components/common/FormField";
import type { AcknowledgeAssignStep } from "@tw/hooks/useAcknowledgeAndAssign";
import type { AssignableGroup, AssignableUserSummary } from "@tw/types";

interface AcknowledgeAssignModalProps {
  open: boolean;
  onClose: () => void;
  step: AcknowledgeAssignStep;
  me: AssignableUserSummary | null;
  groups: AssignableGroup[];
  selectedAgentId: string;
  onSelectAgent: (agentId: string) => void;
  onAcknowledge: () => void;
  onConfirmAssignment: () => void;
  isAcknowledging: boolean;
  isSubmitting: boolean;
}

// Shared by SlaCard.tsx and TicketsListPage.tsx — see
// useAcknowledgeAndAssign.ts for the full two-step reasoning. Two
// distinct steps, not one fused form: assignment is genuinely
// unreachable until acknowledgment succeeds, matching the required
// workflow ("first see an Acknowledge button — until acknowledged,
// cannot assign"). `groups` is role-scoped server-side (see
// EscalationService.get_acknowledge_candidates) — who else appears
// here differs by the caller's own role, rendered as one <optgroup>
// per role.
export function AcknowledgeAssignModal({
  open,
  onClose,
  step,
  me,
  groups,
  selectedAgentId,
  onSelectAgent,
  onAcknowledge,
  onConfirmAssignment,
  isAcknowledging,
  isSubmitting,
}: AcknowledgeAssignModalProps) {
  if (step === "acknowledge") {
    return (
      <Modal
        open={open}
        title="Acknowledge Escalation"
        onClose={onClose}
        footer={
          <Button variant="primary" size="sm" isLoading={isAcknowledging} onClick={onAcknowledge}>
            Acknowledge
          </Button>
        }
      >
        <p className="text-xs text-muted">
          This ticket has escalated to you and is awaiting acknowledgment. Acknowledge it to stop
          it from advancing further up the hierarchy and to start the escalation-handling SLA —
          you&apos;ll then be able to choose who owns it going forward.
        </p>
      </Modal>
    );
  }

  return (
    <Modal
      open={open}
      title="Assign Escalated Ticket"
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          size="sm"
          isLoading={isSubmitting}
          disabled={!selectedAgentId}
          onClick={onConfirmAssignment}
        >
          Confirm
        </Button>
      }
    >
      <p className="mb-3 flex items-center gap-1.5 text-xs text-success">
        <CheckCircle2 size={13} /> Acknowledged — now decide who owns it going forward.
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
