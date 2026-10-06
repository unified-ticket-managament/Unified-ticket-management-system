import { useEffect, useMemo, useState } from "react";
import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput, TextArea } from "@tw/components/common/FormField";
import { SearchableSelect, type SearchableSelectOption } from "@tw/components/common/SearchableSelect";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { transferTicketAgent, updateTicket } from "@tw/api/ticket";
import { formatAssigneeLabel } from "@tw/lib/format";

// Bulk counterparts of the single-ticket Assign/Transfer (TicketActions.tsx)
// and Categorize (ticket_type field on PATCH /tickets/{id}, gated by
// ticket:change_category) actions — each just loops the same existing
// per-ticket API call across the selected ids. No new backend endpoint.

interface BulkAssignDialogProps {
  open: boolean;
  ticketIds: string[];
  onClose: () => void;
  onDone: () => void;
}

export function BulkAssignTicketsDialog({ open, ticketIds, onClose, onDone }: BulkAssignDialogProps) {
  const { agents } = useWorkflowContext();
  const { pushToast } = useToast();
  const [agentId, setAgentId] = useState("");
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setAgentId("");
      setReason("");
    }
  }, [open]);

  const options = useMemo<SearchableSelectOption[]>(
    () =>
      agents.map((agent) => ({
        value: agent.user_id,
        label: formatAssigneeLabel(agent),
        searchText: `${agent.name} ${agent.employee_number ?? ""}`.toLowerCase(),
        group: "",
      })),
    [agents]
  );

  async function handleConfirm() {
    if (!agentId || !reason.trim()) return;
    setIsSubmitting(true);
    const results = await Promise.allSettled(
      ticketIds.map((ticketId) =>
        transferTicketAgent(ticketId, { new_agent_id: agentId, reason: reason.trim() })
      )
    );
    setIsSubmitting(false);
    const failed = results.filter((r) => r.status === "rejected").length;
    const succeeded = results.length - failed;
    pushToast(
      failed === 0
        ? `${succeeded} ticket${succeeded === 1 ? "" : "s"} assigned.`
        : `${succeeded} assigned, ${failed} failed.`,
      failed === 0 ? "success" : "error"
    );
    onClose();
    onDone();
  }

  return (
    <Modal
      open={open}
      title={`Assign ${ticketIds.length} ticket${ticketIds.length === 1 ? "" : "s"}`}
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          size="sm"
          isLoading={isSubmitting}
          disabled={!agentId || !reason.trim()}
          onClick={handleConfirm}
        >
          Assign
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <SearchableSelect
          label="Assign to"
          placeholder="Search by name or employee ID…"
          options={options}
          value={agentId}
          onChange={setAgentId}
          emptyMessage="No matching users found."
        />
        <TextArea
          label="Reason"
          hint="Why are these tickets being assigned? Recorded on each ticket's audit log."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Workload balancing"
        />
      </div>
    </Modal>
  );
}

interface BulkCategorizeDialogProps {
  open: boolean;
  ticketIds: string[];
  onClose: () => void;
  onDone: () => void;
}

export function BulkCategorizeTicketsDialog({
  open,
  ticketIds,
  onClose,
  onDone,
}: BulkCategorizeDialogProps) {
  const { categories } = useWorkflowContext();
  const { pushToast } = useToast();
  const [category, setCategory] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) setCategory("");
  }, [open]);

  async function handleConfirm() {
    if (!category) return;
    setIsSubmitting(true);
    const results = await Promise.allSettled(
      ticketIds.map((ticketId) => updateTicket(ticketId, { ticket_type: category }))
    );
    setIsSubmitting(false);
    const failed = results.filter((r) => r.status === "rejected").length;
    const succeeded = results.length - failed;
    pushToast(
      failed === 0
        ? `${succeeded} ticket${succeeded === 1 ? "" : "s"} moved to ${category}.`
        : `${succeeded} moved, ${failed} failed.`,
      failed === 0 ? "success" : "error"
    );
    onClose();
    onDone();
  }

  return (
    <Modal
      open={open}
      title={`Categorize ${ticketIds.length} ticket${ticketIds.length === 1 ? "" : "s"}`}
      onClose={onClose}
      footer={
        <Button variant="primary" size="sm" isLoading={isSubmitting} disabled={!category} onClick={handleConfirm}>
          Move
        </Button>
      }
    >
      <SelectInput label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
        <option value="">Select a category…</option>
        {categories.map((c) => (
          <option key={c.category_id} value={c.category_name}>
            {c.category_name}
          </option>
        ))}
      </SelectInput>
    </Modal>
  );
}
