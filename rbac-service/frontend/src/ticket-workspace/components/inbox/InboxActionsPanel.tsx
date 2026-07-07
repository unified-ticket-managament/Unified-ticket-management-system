import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCheck,
  FilePlus,
  Link2,
  PencilLine,
  UserPlus,
} from "lucide-react";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput, TextInput } from "@tw/components/common/FormField";
import { useApiAction } from "@tw/hooks/useApiAction";
import {
  attachInteractionToTicket,
  createTicketFromInteraction,
} from "@tw/api/ticket";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { TicketCategory, TicketPriority } from "@tw/types";

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];
const CATEGORIES: TicketCategory[] = ["TECHNICAL", "BILLING", "HIRING", "GENERAL"];

export function InboxActionsPanel() {
  const navigate = useNavigate();
  const { selectedEmail } = useWorkflowContext();

  const [createOpen, setCreateOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);

  const [title, setTitle] = useState("");
  const [ticketType, setTicketType] = useState<TicketCategory>("TECHNICAL");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [existingTicketId, setExistingTicketId] = useState("");

  const { run: runCreate, isLoading: isCreating } = useApiAction(
    createTicketFromInteraction,
    { successMessage: "Ticket created from this email." }
  );
  const { run: runAttach, isLoading: isAttaching } = useApiAction(
    attachInteractionToTicket,
    { successMessage: "Email attached to existing ticket." }
  );

  if (!selectedEmail) {
    return (
      <div className="flex h-full items-center justify-center rounded-md2 border border-border bg-surface shadow-xs">
        <EmptyState
          icon="⚡"
          title="No email selected"
          description="Actions become available once you open an email."
        />
      </div>
    );
  }

  async function handleCreateTicket() {
    if (!selectedEmail) return;

    const result = await runCreate({
      interaction_id: selectedEmail.interaction_id,
      title: title || selectedEmail.subject,
      ticket_type: ticketType,
      current_priority: priority,
    });

    if (result) {
      setCreateOpen(false);
      navigate(`/tickets/${result.ticket_id}`);
    }
  }

  async function handleAttachExisting() {
    if (!selectedEmail || !existingTicketId) return;

    const result = await runAttach(existingTicketId, {
      interaction_id: selectedEmail.interaction_id,
    });

    if (result) {
      setAttachOpen(false);
      navigate(`/tickets/${result.ticket_id}`);
    }
  }

  return (
    <>
      <div className="flex h-full flex-col gap-3 rounded-md2 border border-border bg-surface p-4 shadow-xs">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">Actions</h3>
          <p className="text-[11px] text-muted">What would you like to do?</p>
        </div>

        <button
          onClick={() => setCreateOpen(true)}
          className="group flex items-center gap-3 rounded-md2 border border-success/20 bg-success/5 px-4 py-3.5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-success/30 hover:bg-success/10 hover:shadow-xs"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-success/15 text-success">
            <FilePlus size={16} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-slate-900">Create New Ticket</p>
            <p className="text-[11px] text-muted">Create a new ticket from this email</p>
          </div>
        </button>

        <button
          onClick={() => setAttachOpen(true)}
          className="group flex items-center gap-3 rounded-md2 border border-accent/20 bg-accent/5 px-4 py-3.5 text-left transition-all duration-150 hover:-translate-y-0.5 hover:border-accent/30 hover:bg-accent/10 hover:shadow-xs"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-accent/15 text-accent">
            <Link2 size={16} />
          </div>
          <div>
            <p className="text-[13px] font-semibold text-slate-900">
              Attach to Existing Ticket
            </p>
            <p className="text-[11px] text-muted">Link this email to an existing ticket</p>
          </div>
        </button>

        <div
          title="Not available yet — no assign-to-agent endpoint exists for a pending (pre-ticket) interaction."
          className="flex cursor-not-allowed items-center gap-3 rounded-md2 border border-border px-4 py-3.5 text-left opacity-50"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
            <UserPlus size={16} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-slate-700">Assign to Me</p>
            <p className="text-[11px] text-muted">Not available yet</p>
          </div>
        </div>

        <div
          title="Not available yet — no update endpoint exists for a pending (pre-ticket) interaction."
          className="flex cursor-not-allowed items-center gap-3 rounded-md2 border border-border px-4 py-3.5 text-left opacity-50"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
            <PencilLine size={16} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-slate-700">Update Email</p>
            <p className="text-[11px] text-muted">Not available yet</p>
          </div>
        </div>

        <div
          title="Not available yet — no read-status endpoint exists for a pending (pre-ticket) interaction."
          className="flex cursor-not-allowed items-center gap-3 rounded-md2 border border-border px-4 py-3.5 text-left opacity-50"
        >
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-canvas text-muted">
            <CheckCheck size={16} />
          </div>
          <div>
            <p className="text-[13px] font-medium text-slate-700">Mark as Read</p>
            <p className="text-[11px] text-muted">Not available yet</p>
          </div>
        </div>
      </div>

      <Modal
        open={createOpen}
        title="Create Ticket From This Email"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isCreating}
              onClick={handleCreateTicket}
            >
              Create Ticket
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <TextInput
            label="Title"
            placeholder={selectedEmail.subject}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <SelectInput
            label="Category"
            value={ticketType}
            onChange={(e) => setTicketType(e.target.value as TicketCategory)}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </SelectInput>
          <SelectInput
            label="Priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as TicketPriority)}
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </SelectInput>
        </div>
      </Modal>

      <Modal
        open={attachOpen}
        title="Attach To Existing Ticket"
        onClose={() => setAttachOpen(false)}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={() => setAttachOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              isLoading={isAttaching}
              onClick={handleAttachExisting}
            >
              Attach
            </Button>
          </>
        }
      >
        <TextInput
          label="Existing ticket ID"
          placeholder="Paste a ticket_id"
          value={existingTicketId}
          onChange={(e) => setExistingTicketId(e.target.value)}
        />
      </Modal>
    </>
  );
}
