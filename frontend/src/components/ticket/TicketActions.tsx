import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeftRight, Paperclip, Flame, MessageSquareText, Send, Settings2 } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Modal } from "@/components/common/Modal";
import { SelectInput, TextArea, TextInput } from "@/components/common/FormField";
import { useApiAction } from "@/hooks/useApiAction";
import {
  addInternalNote,
  changeTicketPriority,
  changeTicketStatus,
  replyToClient,
  uploadAttachment,
} from "@/api/interaction";
import { listAgents } from "@/api/agent";
import { transferTicketAgent } from "@/api/ticket";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { AgentSummary, TicketPriority, TicketStatus } from "@/types";

const STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
  "CLOSED",
];

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

type Tone = "accent" | "warning" | "info" | "danger" | "default";

const tileToneClasses: Record<Tone, string> = {
  accent: "bg-accent/10 text-accent group-hover:bg-accent/15",
  warning: "bg-warning/10 text-warning group-hover:bg-warning/15",
  info: "bg-info/10 text-info group-hover:bg-info/15",
  danger: "bg-danger/10 text-danger group-hover:bg-danger/15",
  default: "bg-canvas text-slate-600 group-hover:bg-slate-200/60",
};

function ActionTile({
  icon,
  label,
  tone,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  tone: Tone;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex flex-col items-center gap-2 rounded-md2 border border-border bg-surface px-3 py-4 text-center transition-all duration-150 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-cardHover"
    >
      <span className={`flex h-9 w-9 items-center justify-center rounded-md2 transition-colors ${tileToneClasses[tone]}`}>
        {icon}
      </span>
      <span className="text-[11px] font-semibold leading-tight text-slate-700">{label}</span>
    </button>
  );
}

type ActiveModal =
  | "note"
  | "reply"
  | "status"
  | "priority"
  | "transfer"
  | "attachment"
  | null;

interface TicketActionsProps {
  onActionComplete: () => void;
}

export function TicketActions({ onActionComplete }: TicketActionsProps) {
  const { activeTicket } = useWorkflowContext();
  const [modal, setModal] = useState<ActiveModal>(null);

  const [note, setNote] = useState("");
  const [replyMessage, setReplyMessage] = useState("");
  const [newStatus, setNewStatus] = useState<TicketStatus>("IN_PROGRESS");
  const [newPriority, setNewPriority] = useState<TicketPriority>("HIGH");
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [newAgentId, setNewAgentId] = useState("");
  const [filename, setFilename] = useState("screenshot.png");
  const [storageKey, setStorageKey] = useState("uploads/demo/screenshot.png");

  const { run: runNote, isLoading: isNoteLoading } = useApiAction(addInternalNote, {
    successMessage: "Internal note added.",
  });
  const { run: runReply, isLoading: isReplyLoading } = useApiAction(replyToClient, {
    successMessage: "Reply sent to client.",
  });
  const { run: runStatus, isLoading: isStatusLoading } = useApiAction(changeTicketStatus, {
    successMessage: "Ticket status changed.",
  });
  const { run: runPriority, isLoading: isPriorityLoading } = useApiAction(
    changeTicketPriority,
    { successMessage: "Ticket priority changed." }
  );
  const { run: runTransfer, isLoading: isTransferLoading } = useApiAction(
    transferTicketAgent,
    { successMessage: (res) => res.message }
  );
  const { run: runUpload, isLoading: isUploadLoading } = useApiAction(uploadAttachment, {
    successMessage: "Attachment uploaded.",
  });

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch(() => setAgents([]));
  }, []);

  if (!activeTicket) return null;

  const transferCandidates = agents.filter((a) => a.user_id !== activeTicket.agent_id);

  function closeModal() {
    setModal(null);
  }

  function openTransferModal() {
    setNewAgentId(transferCandidates[0]?.user_id ?? "");
    setModal("transfer");
  }

  async function handleAddNote() {
    const result = await runNote(activeTicket!.ticket_id, { note });
    if (result) {
      setNote("");
      closeModal();
      onActionComplete();
    }
  }

  async function handleReply() {
    const result = await runReply(activeTicket!.ticket_id, { message: replyMessage });
    if (result) {
      setReplyMessage("");
      closeModal();
      onActionComplete();
    }
  }

  async function handleStatusChange() {
    const result = await runStatus(activeTicket!.ticket_id, { new_status: newStatus });
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  async function handlePriorityChange() {
    const result = await runPriority(activeTicket!.ticket_id, { new_priority: newPriority });
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  async function handleTransferAgent() {
    if (!newAgentId) return;
    const result = await runTransfer(activeTicket!.ticket_id, { new_agent_id: newAgentId });
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  async function handleUpload() {
    const result = await runUpload(activeTicket!.ticket_id, {
      filename,
      storage_key: storageKey,
      mime_type: "image/png",
      size_bytes: 204800,
    });
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  return (
    <>
      <Card title="Actions" eyebrow="Ticket tools">
        <div className="grid grid-cols-2 gap-2.5">
          <ActionTile icon={<Send size={16} />} label="Reply" tone="accent" onClick={() => setModal("reply")} />
          <ActionTile
            icon={<MessageSquareText size={16} />}
            label="Internal Note"
            tone="warning"
            onClick={() => setModal("note")}
          />
          <ActionTile
            icon={<Settings2 size={16} />}
            label="Change Status"
            tone="info"
            onClick={() => setModal("status")}
          />
          <ActionTile
            icon={<Flame size={16} />}
            label="Change Priority"
            tone="danger"
            onClick={() => setModal("priority")}
          />
          <ActionTile
            icon={<ArrowLeftRight size={16} />}
            label="Transfer Agent"
            tone="accent"
            onClick={openTransferModal}
          />
          <ActionTile
            icon={<Paperclip size={16} />}
            label="Upload Attachment"
            tone="default"
            onClick={() => setModal("attachment")}
          />
        </div>
      </Card>

      <Modal
        open={modal === "note"}
        title="Add Internal Note"
        onClose={closeModal}
        footer={
          <Button variant="primary" size="sm" isLoading={isNoteLoading} onClick={handleAddNote}>
            Add Note
          </Button>
        }
      >
        <TextArea
          label="Note (visible to agents only)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </Modal>

      <Modal
        open={modal === "reply"}
        title="Reply To Client"
        onClose={closeModal}
        footer={
          <Button variant="primary" size="sm" isLoading={isReplyLoading} onClick={handleReply}>
            Send Reply
          </Button>
        }
      >
        <TextArea
          label="Message"
          value={replyMessage}
          onChange={(e) => setReplyMessage(e.target.value)}
        />
      </Modal>

      <Modal
        open={modal === "status"}
        title="Change Ticket Status"
        onClose={closeModal}
        footer={
          <Button variant="primary" size="sm" isLoading={isStatusLoading} onClick={handleStatusChange}>
            Update Status
          </Button>
        }
      >
        <SelectInput
          label="New status"
          value={newStatus}
          onChange={(e) => setNewStatus(e.target.value as TicketStatus)}
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </SelectInput>
      </Modal>

      <Modal
        open={modal === "priority"}
        title="Change Ticket Priority"
        onClose={closeModal}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isPriorityLoading}
            onClick={handlePriorityChange}
          >
            Update Priority
          </Button>
        }
      >
        <SelectInput
          label="New priority"
          value={newPriority}
          onChange={(e) => setNewPriority(e.target.value as TicketPriority)}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </SelectInput>
      </Modal>

      <Modal
        open={modal === "transfer"}
        title="Transfer Agent"
        onClose={closeModal}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isTransferLoading}
            disabled={!newAgentId}
            onClick={handleTransferAgent}
          >
            Transfer
          </Button>
        }
      >
        {transferCandidates.length === 0 ? (
          <p className="text-sm text-muted">No other active agents to transfer to.</p>
        ) : (
          <>
            <SelectInput
              label="Transfer to"
              value={newAgentId}
              onChange={(e) => setNewAgentId(e.target.value)}
            >
              {transferCandidates.map((agent) => (
                <option key={agent.user_id} value={agent.user_id}>
                  {agent.name}
                </option>
              ))}
            </SelectInput>
            <p className="mt-2 text-[11px] text-muted">
              {activeTicket.agent_name ?? "The current agent"} will lose all access to this
              ticket the moment it's transferred — ownership moves fully to the new agent.
            </p>
          </>
        )}
      </Modal>

      <Modal
        open={modal === "attachment"}
        title="Upload Attachment"
        onClose={closeModal}
        footer={
          <Button variant="primary" size="sm" isLoading={isUploadLoading} onClick={handleUpload}>
            Upload
          </Button>
        }
      >
        <div className="flex flex-col gap-3">
          <TextInput
            label="Filename"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
          />
          <TextInput
            label="Storage key"
            value={storageKey}
            onChange={(e) => setStorageKey(e.target.value)}
            hint="Placeholder path — no real file storage is wired up yet."
          />
        </div>
      </Modal>
    </>
  );
}
