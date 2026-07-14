"use client";

import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput } from "@tw/components/common/FormField";
import type { AgentSummary } from "@tw/types";

interface AcknowledgeAssignModalProps {
  open: boolean;
  onClose: () => void;
  candidates: AgentSummary[];
  selectedAgentId: string;
  onSelectAgent: (agentId: string) => void;
  onConfirm: () => void;
  isSubmitting: boolean;
}

// Shared by SlaCard.tsx and TicketsListPage.tsx — see
// useAcknowledgeAndAssign.ts for why acknowledging an escalation
// always also requires picking who owns the ticket going forward.
export function AcknowledgeAssignModal({
  open,
  onClose,
  candidates,
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
        {candidates.map((agent) => (
          <option key={agent.user_id} value={agent.user_id}>
            {agent.name}
          </option>
        ))}
      </SelectInput>
    </Modal>
  );
}
