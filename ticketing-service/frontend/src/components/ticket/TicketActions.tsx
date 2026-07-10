import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeftRight,
  Paperclip,
  Flame,
  MessageSquareText,
  Send,
  Settings2,
} from "lucide-react";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { Modal } from "@/components/common/Modal";
import { SelectInput } from "@/components/common/FormField";
import { FileDropzone } from "@/components/common/FileDropzone";
import { validateFiles } from "@/lib/attachmentMeta";
import { useApiAction } from "@/hooks/useApiAction";
import {
  changeTicketPriority,
  changeTicketStatus,
  uploadAttachment,
} from "@/api/interaction";
import { listAgents } from "@/api/agent";
import { listEditAccessRequests, transferTicketAgent } from "@/api/ticket";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type {
  AgentSummary,
  EditAccessRequestResponse,
  TicketPriority,
  TicketStatus,
} from "@/types";
import type { ComposerMode } from "@/components/ticket/TicketComposer";

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
  disabled,
  title,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  tone: Tone;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="group flex flex-col items-center gap-2 rounded-md2 border border-border bg-surface px-3 py-4 text-center transition-all duration-150 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-cardHover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:shadow-none"
    >
      <span className={`flex h-9 w-9 items-center justify-center rounded-md2 transition-colors ${tileToneClasses[tone]}`}>
        {icon}
      </span>
      <span className="text-[11px] font-semibold leading-tight text-slate-700">{label}</span>
    </button>
  );
}

type ActiveModal = "status" | "priority" | "transfer" | "attachment" | null;

interface TicketActionsProps {
  onActionComplete: () => void;
  onOpenComposer: (mode: ComposerMode) => void;
}

export function TicketActions({ onActionComplete, onOpenComposer }: TicketActionsProps) {
  const { activeTicket } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [modal, setModal] = useState<ActiveModal>(null);

  const [newStatus, setNewStatus] = useState<TicketStatus>("IN_PROGRESS");
  const [newPriority, setNewPriority] = useState<TicketPriority>("HIGH");
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [newAgentId, setNewAgentId] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [editAccessRequests, setEditAccessRequests] = useState<EditAccessRequestResponse[]>([]);

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
    successMessage: (res) =>
      `${res.attachments.length} file${res.attachments.length === 1 ? "" : "s"} uploaded.`,
  });
  const { run: runListEditAccess } = useApiAction(listEditAccessRequests);

  useEffect(() => {
    if (!activeTicket) return;
    // Scoped to the ticket's own work-specialization category — a
    // Team Lead assigning/transferring should only see their own
    // team's Staff, not every Staff member company-wide.
    listAgents(activeTicket.ticket_type)
      .then(setAgents)
      .catch(() => setAgents([]));
  }, [activeTicket?.ticket_id, activeTicket?.ticket_type]);

  useEffect(() => {
    if (!activeTicket) return;
    runListEditAccess(activeTicket.ticket_id).then((result) => {
      if (result) setEditAccessRequests(result);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id]);

  if (!activeTicket) return null;

  const isStaff = currentUser?.role === "Staff";
  const canChangePriority = (currentUser?.permissions ?? []).includes(
    "ticket:change_priority"
  );
  const canTransfer = isStaff
    ? (currentUser?.permissions ?? []).includes("ticket:transfer")
    : true;
  const isUnclaimed = activeTicket.agent_id == null;
  const transferCandidates = agents.filter((a) => a.user_id !== activeTicket.agent_id);
  // Closed is terminal for every action except Change Status itself —
  // that's the only way to reopen a closed ticket, so it stays enabled.
  const isTicketClosed = activeTicket.current_status === "CLOSED";

  // Mirrors the backend's ensure_agent_can_act_on_ticket: the assigned
  // agent, anyone holding ticket:editother_ticket (globally or scoped to
  // this specific ticket via scoped_permissions), or anyone with an
  // active, approved Edit Access grant on this ticket. Reply/Internal
  // Note/Change Status/Upload Attachment all disable-in-place (not hide)
  // when none of these hold, so a user without access sees why rather
  // than discovering it via a rejected request after typing a reply.
  const isOwnTicket = activeTicket.agent_id === currentUser?.user_id;
  const hasEditOther =
    (currentUser?.permissions ?? []).includes("ticket:editother_ticket") ||
    (currentUser?.scoped_permissions?.["ticket:editother_ticket"] ?? []).includes(
      activeTicket.ticket_id
    );
  const hasActiveEditAccessGrant = editAccessRequests.some(
    (r) =>
      r.requested_by === currentUser?.user_id &&
      r.status === "APPROVED" &&
      (!r.expires_at || new Date(r.expires_at) > new Date())
  );
  const canActOnTicket = isOwnTicket || hasEditOther || hasActiveEditAccessGrant;
  const noAccessTitle = canActOnTicket
    ? undefined
    : "You don't have access to work on this ticket";

  function closeModal() {
    setModal(null);
  }

  function openTransferModal() {
    setNewAgentId(transferCandidates[0]?.user_id ?? "");
    setModal("transfer");
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
    const result = await runUpload(activeTicket!.ticket_id, uploadFiles);
    if (result) {
      setUploadFiles([]);
      closeModal();
      onActionComplete();
    }
  }

  return (
    <>
      <Card title="Actions" eyebrow="Ticket tools">
        <div className="grid grid-cols-2 gap-2.5">
          <ActionTile
            icon={<Send size={16} />}
            label="Reply"
            tone="accent"
            disabled={isTicketClosed || !canActOnTicket}
            title={noAccessTitle}
            onClick={() => onOpenComposer("reply")}
          />
          <ActionTile
            icon={<MessageSquareText size={16} />}
            label="Internal Note"
            tone="warning"
            disabled={isTicketClosed || !canActOnTicket}
            title={noAccessTitle}
            onClick={() => onOpenComposer("note")}
          />
          <ActionTile
            icon={<Settings2 size={16} />}
            label="Change Status"
            tone="info"
            disabled={!canActOnTicket}
            title={noAccessTitle}
            onClick={() => setModal("status")}
          />
          <ActionTile
            icon={<Flame size={16} />}
            label="Change Priority"
            tone="danger"
            disabled={isTicketClosed || !canChangePriority}
            title={canChangePriority ? undefined : "Requires the Change Priority permission"}
            onClick={() => setModal("priority")}
          />
          {(!isStaff || canTransfer) && (
            <ActionTile
              icon={<ArrowLeftRight size={16} />}
              label={isUnclaimed ? "Assign to Staff" : "Transfer Agent"}
              tone="accent"
              disabled={isTicketClosed}
              onClick={openTransferModal}
            />
          )}
          <ActionTile
            icon={<Paperclip size={16} />}
            label="Upload Attachment"
            tone="default"
            disabled={isTicketClosed || !canActOnTicket}
            title={noAccessTitle}
            onClick={() => setModal("attachment")}
          />
        </div>
      </Card>

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
        title={isUnclaimed ? "Assign to Staff" : "Transfer Agent"}
        onClose={closeModal}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isTransferLoading}
            disabled={!newAgentId}
            onClick={handleTransferAgent}
          >
            {isUnclaimed ? "Assign" : "Transfer"}
          </Button>
        }
      >
        {transferCandidates.length === 0 ? (
          <p className="text-sm text-muted">
            No active Staff in the "{activeTicket.ticket_type}" category to
            {isUnclaimed ? " assign this to" : " transfer to"}.
          </p>
        ) : (
          <>
            <SelectInput
              label={isUnclaimed ? "Assign to" : "Transfer to"}
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
              {isUnclaimed
                ? `Only Staff in the "${activeTicket.ticket_type}" category are listed.`
                : `${activeTicket.agent_name ?? "The current agent"} will lose all access to this ticket the moment it's transferred — ownership moves fully to the new agent.`}
            </p>
          </>
        )}
      </Modal>

      <Modal
        open={modal === "attachment"}
        title="Upload Attachment"
        onClose={closeModal}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isUploadLoading}
            disabled={uploadFiles.length === 0 || validateFiles(uploadFiles).errors.length > 0}
            onClick={handleUpload}
          >
            Upload
          </Button>
        }
      >
        <FileDropzone label="Files" files={uploadFiles} onFilesChange={setUploadFiles} />
      </Modal>
    </>
  );
}
