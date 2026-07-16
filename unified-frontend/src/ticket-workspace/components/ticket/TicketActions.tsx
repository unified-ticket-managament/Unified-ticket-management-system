import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  CheckCircle2,
  ChevronDown,
  Flame,
  Lock,
  MessagesSquare,
  Paperclip,
  RotateCcw,
  Settings2,
  ShieldCheck,
  UserPlus,
} from "lucide-react";
import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput, TextArea } from "@tw/components/common/FormField";
import { FileDropzone } from "@tw/components/common/FileDropzone";
import { EditAccessPanel } from "@tw/components/ticket/EditAccessPanel";
import { validateFiles } from "@tw/lib/attachmentMeta";
import { useApiAction } from "@tw/hooks/useApiAction";
import {
  changeTicketPriority,
  changeTicketStatus,
  uploadAttachment,
} from "@tw/api/interaction";
import { listAgents } from "@tw/api/agent";
import { claimTicket, closeTicket, reopenTicket, transferTicketAgent } from "@tw/api/ticket";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { AgentSummary, TicketPriority, TicketStatus } from "@tw/types";

// CLOSED is deliberately absent — closing a ticket only happens via
// the dedicated Close Ticket action (More menu), never through this
// dropdown. Reopening is likewise its own dedicated Reopen Ticket
// action, not a status value picked here.
const STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
];

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

type ActiveModal =
  | "status"
  | "priority"
  | "transfer"
  | "attachment"
  | "editAccess"
  | "close"
  | "reopen"
  | null;

interface TicketActionsProps {
  onActionComplete: () => void;
}

// Renders only the top-right action row (Change Status / Change
// Priority / Claim / More ▼) — Reply and Internal Note used to be
// tiles here too, but now live as their own tabs in
// TicketActivityPanel instead (see TicketDetailPage). Every modal,
// permission check, and API call below is unchanged from before; only
// the trigger markup moved.
export function TicketActions({ onActionComplete }: TicketActionsProps) {
  const navigate = useNavigate();
  // editAccessRequests is fetched once per ticket by TicketDetailPage
  // and shared via context with EditAccessPanel — see that context
  // field's own comment for why this used to be a separate
  // GET /tickets/{id}/edit-access call from each component.
  const { activeTicket, editAccessRequests } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [modal, setModal] = useState<ActiveModal>(null);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);

  const [newStatus, setNewStatus] = useState<TicketStatus>("IN_PROGRESS");
  const [newPriority, setNewPriority] = useState<TicketPriority>("HIGH");
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [newAgentId, setNewAgentId] = useState("");
  const [transferReason, setTransferReason] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);

  const { run: runStatus, isLoading: isStatusLoading } = useApiAction(changeTicketStatus, {
    successMessage: "Ticket status changed.",
  });
  const { run: runPriority, isLoading: isPriorityLoading } = useApiAction(
    changeTicketPriority,
    { successMessage: "Ticket priority changed." }
  );
  const { run: runClaim, isLoading: isClaimLoading } = useApiAction(claimTicket, {
    successMessage: "Ticket claimed.",
  });
  const { run: runTransfer, isLoading: isTransferLoading } = useApiAction(
    transferTicketAgent,
    { successMessage: (res) => res.message }
  );
  const { run: runUpload, isLoading: isUploadLoading } = useApiAction(uploadAttachment, {
    successMessage: (res) =>
      `${res.attachments.length} file${res.attachments.length === 1 ? "" : "s"} uploaded.`,
  });
  const { run: runClose, isLoading: isCloseLoading } = useApiAction(closeTicket, {
    successMessage: (res) => res.message,
  });
  const { run: runReopen, isLoading: isReopenLoading } = useApiAction(reopenTicket, {
    successMessage: (res) => res.message,
  });

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
    if (!isMoreOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (moreRef.current && !moreRef.current.contains(event.target as Node)) {
        setIsMoreOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isMoreOpen]);

  if (!activeTicket) return null;

  const isStaff = currentUser?.role === "Staff";
  const isCloseReopenBypassRole =
    currentUser?.role === "Site Lead" || currentUser?.role === "Super Admin";
  const canChangePriority = (currentUser?.permissions ?? []).includes(
    "ticket:change_priority"
  );
  const canTransfer = isStaff
    ? (currentUser?.permissions ?? []).includes("ticket:transfer")
    : true;
  // Mirrors the backend's ensure_can_close_ticket/ensure_can_reopen_ticket
  // hybrid gates exactly: only Site Lead/Super Admin bypass via role —
  // Account Manager, Team Lead, and Staff all fall through to the real
  // permission (Full for Account Manager, override-only for the other two,
  // per the RBAC matrix doc).
  const canClose = isCloseReopenBypassRole
    ? true
    : (currentUser?.permissions ?? []).includes("ticket:close_ticket");
  const canReopen = isCloseReopenBypassRole
    ? true
    : (currentUser?.permissions ?? []).includes("ticket:reopen");
  const isUnclaimed = activeTicket.agent_id == null;
  // Excludes the caller themselves — self-assignment goes through the
  // dedicated Claim tile (POST /tickets/{id}/claim) so it's recorded as
  // a CLAIM interaction/TICKET_CLAIMED audit event, not an
  // AGENT_TRANSFER — picking yourself here would otherwise call
  // transferTicketAgent and misrecord a claim as a transfer.
  const transferCandidates = agents.filter(
    (a) => a.user_id !== activeTicket.agent_id && a.user_id !== currentUser?.user_id
  );
  // Closed is now terminal for every action, including Change Status —
  // Reopen Ticket (its own dedicated, permission-gated action) is the
  // only way off CLOSED.
  const isTicketClosed = activeTicket.current_status === "CLOSED";

  // Mirrors the backend's ensure_agent_can_act_on_ticket: the assigned
  // agent, anyone holding ticket:editother_ticket (globally or scoped to
  // this specific ticket via scoped_permissions), or anyone with an
  // active, approved Edit Access grant on this ticket. Change Status/
  // Upload Attachment disable-in-place (not hide) when none of these
  // hold, so a user without access sees why rather than discovering it
  // via a rejected request.
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
  // An actively (not yet acknowledged) escalated ticket is frozen for
  // its currently-assigned agent — mirrors the backend's own new gate
  // in ensure_agent_can_act_on_ticket. Supervisors are exempt here too
  // (same bypass the backend grants them) — acknowledging/assigning is
  // how a supervisor is meant to interact with an active escalation,
  // not this "work it normally" set of actions.
  const SUPERVISOR_ROLES = new Set(["Team Lead", "Account Manager", "Site Lead", "Super Admin"]);
  const isSupervisor = !!currentUser && SUPERVISOR_ROLES.has(currentUser.role);
  const isFrozenByEscalation =
    !isSupervisor &&
    activeTicket.is_escalated &&
    activeTicket.escalation_status === "ACTIVE";
  const canActOnTicket =
    !isFrozenByEscalation && (isOwnTicket || hasEditOther || hasActiveEditAccessGrant);
  const noAccessTitle = isFrozenByEscalation
    ? "This ticket has been escalated and is awaiting acknowledgment — it cannot be worked until reassigned"
    : canActOnTicket
      ? undefined
      : "You don't have access to work on this ticket";

  function closeModal() {
    setModal(null);
  }

  function openMoreItem(next: Exclude<ActiveModal, null>) {
    setIsMoreOpen(false);
    setModal(next);
  }

  function openTransferModal() {
    setNewAgentId(transferCandidates[0]?.user_id ?? "");
    setTransferReason("");
    openMoreItem("transfer");
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

  async function handleClaim() {
    const result = await runClaim(activeTicket!.ticket_id);
    if (result) {
      onActionComplete();
    }
  }

  async function handleTransferAgent() {
    if (!newAgentId || !transferReason.trim()) return;
    const result = await runTransfer(activeTicket!.ticket_id, {
      new_agent_id: newAgentId,
      reason: transferReason.trim(),
    });
    if (result) {
      setTransferReason("");
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

  async function handleClose() {
    const result = await runClose(activeTicket!.ticket_id);
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  async function handleReopen() {
    const result = await runReopen(activeTicket!.ticket_id);
    if (result) {
      closeModal();
      onActionComplete();
    }
  }

  const menuItemClass =
    "flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] font-medium text-slate-700 transition-colors hover:bg-surfaceHover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent";

  return (
    <>
      <div className="flex flex-none flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={isTicketClosed || !canActOnTicket}
          title={isTicketClosed ? "This ticket is closed" : noAccessTitle}
          onClick={() => setModal("status")}
        >
          <Settings2 size={14} />
          Change Status
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={isTicketClosed || isFrozenByEscalation || !canChangePriority}
          title={
            isFrozenByEscalation
              ? noAccessTitle
              : canChangePriority
                ? undefined
                : "Requires the Change Priority permission"
          }
          onClick={() => setModal("priority")}
        >
          <Flame size={14} />
          Change Priority
        </Button>
        {isUnclaimed && (
          <Button
            variant="secondary"
            size="sm"
            disabled={isTicketClosed || isFrozenByEscalation || isClaimLoading}
            title={isFrozenByEscalation ? noAccessTitle : undefined}
            isLoading={isClaimLoading}
            onClick={handleClaim}
          >
            <UserPlus size={14} />
            Claim Ticket
          </Button>
        )}

        <div className="relative" ref={moreRef}>
          <Button variant="secondary" size="sm" onClick={() => setIsMoreOpen((prev) => !prev)}>
            More
            <ChevronDown size={14} />
          </Button>
          {isMoreOpen && (
            <div className="absolute right-0 z-20 mt-1.5 w-52 overflow-hidden rounded-md2 border border-border bg-surface py-1 shadow-popover animate-fadeSlideIn">
              <button
                type="button"
                className={menuItemClass}
                disabled={isTicketClosed || !canActOnTicket}
                title={noAccessTitle}
                onClick={() => openMoreItem("attachment")}
              >
                <Paperclip size={14} className="text-muted" />
                Upload Attachment
              </button>
              {(!isStaff || canTransfer) && (
                <button
                  type="button"
                  className={menuItemClass}
                  disabled={isTicketClosed || isFrozenByEscalation}
                  title={isTicketClosed ? "This ticket is closed" : noAccessTitle}
                  onClick={openTransferModal}
                >
                  <ArrowLeftRight size={14} className="text-muted" />
                  {isUnclaimed ? "Assign to Staff" : "Transfer Ticket"}
                </button>
              )}
              <button
                type="button"
                className={menuItemClass}
                disabled={isTicketClosed}
                title={isTicketClosed ? "This ticket is closed" : undefined}
                onClick={() => openMoreItem("editAccess")}
              >
                <ShieldCheck size={14} className="text-muted" />
                Edit Access
              </button>
              <button
                type="button"
                className={menuItemClass}
                onClick={() => {
                  setIsMoreOpen(false);
                  navigate(`/tickets/${activeTicket.ticket_id}/interactions`);
                }}
              >
                <MessagesSquare size={14} className="text-muted" />
                Interactions
              </button>
              {!isTicketClosed && (!isStaff || canClose) && (
                <button
                  type="button"
                  className={menuItemClass}
                  onClick={() => openMoreItem("close")}
                >
                  <Lock size={14} className="text-muted" />
                  Close Ticket
                </button>
              )}
              {isTicketClosed && (!isStaff || canReopen) && (
                <button
                  type="button"
                  className={menuItemClass}
                  onClick={() => openMoreItem("reopen")}
                >
                  <RotateCcw size={14} className="text-muted" />
                  Reopen Ticket
                </button>
              )}
            </div>
          )}
        </div>
      </div>

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
        title={isUnclaimed ? "Assign to Staff" : "Transfer Ticket"}
        onClose={closeModal}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={isTransferLoading}
            disabled={!newAgentId || !transferReason.trim()}
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
          <div className="flex flex-col gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
                Current Assignee
              </p>
              <p className="mt-1 text-[13px] font-medium text-slate-800">
                {activeTicket.agent_name ?? "Unassigned"}
              </p>
            </div>
            <SelectInput
              label={isUnclaimed ? "Assign to" : "New Staff"}
              value={newAgentId}
              onChange={(e) => setNewAgentId(e.target.value)}
            >
              {transferCandidates.map((agent) => (
                <option key={agent.user_id} value={agent.user_id}>
                  {agent.name}
                </option>
              ))}
            </SelectInput>
            <TextArea
              label="Reason"
              hint="Why is this ticket being transferred? Recorded on the audit log."
              value={transferReason}
              onChange={(e) => setTransferReason(e.target.value)}
              placeholder="e.g. Workload balancing"
            />
            <p className="text-[11px] text-muted">
              {isUnclaimed
                ? `Only Staff in the "${activeTicket.ticket_type}" category are listed.`
                : `${activeTicket.agent_name ?? "The current agent"} will lose all access to this ticket the moment it's transferred — ownership moves fully to the new agent.`}
            </p>
          </div>
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

      <Modal open={modal === "editAccess"} title="Edit Access" onClose={closeModal}>
        <EditAccessPanel embedded onRequestsChanged={onActionComplete} />
      </Modal>

      <Modal
        open={modal === "close"}
        title="Close Ticket"
        onClose={closeModal}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={closeModal}>
              Cancel
            </Button>
            <Button variant="danger" size="sm" isLoading={isCloseLoading} onClick={handleClose}>
              Close Ticket
            </Button>
          </>
        }
      >
        <p className="flex items-start gap-2 text-sm text-slate-700">
          <Lock size={15} className="mt-0.5 flex-none text-muted" />
          <span>
            Are you sure you want to close this ticket?
            <br />
            Closed tickets become read-only until reopened.
          </span>
        </p>
      </Modal>

      <Modal
        open={modal === "reopen"}
        title="Reopen Ticket"
        onClose={closeModal}
        footer={
          <>
            <Button variant="ghost" size="sm" onClick={closeModal}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" isLoading={isReopenLoading} onClick={handleReopen}>
              Reopen Ticket
            </Button>
          </>
        }
      >
        <p className="flex items-start gap-2 text-sm text-slate-700">
          <CheckCircle2 size={15} className="mt-0.5 flex-none text-muted" />
          Reopen this ticket?
        </p>
      </Modal>
    </>
  );
}
