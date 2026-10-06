import { useCallback, useEffect, useMemo, useState } from "react";
import { Crown, Lock, Plus, Tag, UserMinus, Users, X } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { Modal } from "@tw/components/common/Modal";
import { SelectInput } from "@tw/components/common/FormField";
import { UserMultiSelect, type SelectableUser } from "@tw/components/common/UserMultiSelect";
import { statusTone } from "@tw/lib/ticketTone";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { getTransferCandidates } from "@tw/api/ticket";
import {
  addTicketCategory,
  assignTicketUsers,
  getTicketAssignments,
  removeTicketAssignment,
  removeTicketCategory,
  updateTicketAssignment,
} from "@tw/api/assignment";
import type {
  AssignableAgentsResponse,
  AssignmentSLARunState,
  TicketAssignmentItem,
  TicketAssignmentsResponse,
  TicketStatus,
} from "@tw/types";

// Mirrors the backend's SUPERVISOR_ROLE_NAMES (access_control.py). Used
// only to decide which controls to SHOW — the backend re-checks every
// action (RBAC is authoritative; nothing here grants anything).
const SUPERVISOR_ROLES = new Set(["Team Lead", "Account Manager", "Site Lead", "Super Admin"]);

// An assignee's OWN status. CLOSED is never offered — only the Close
// Ticket action closes (and it closes every assignment at once).
const ASSIGNMENT_STATUSES: TicketStatus[] = [
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
  "RESOLVED",
];

const STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In Progress",
  PENDING: "Pending",
  WAITING_FOR_CLIENT: "Waiting for Client",
  RESOLVED: "Resolved",
  CLOSED: "Closed",
};

export function formatDuration(totalSeconds: number): string {
  const seconds = Math.abs(totalSeconds);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

// "3h 10m remaining" / "Completed" / "Breached" / "Paused" — one
// assignee's own Resolution SLA, never a category's.
export function describeAssignmentSla(run: AssignmentSLARunState | null): {
  label: string;
  tone: "success" | "warning" | "danger" | "info" | "default";
} {
  if (!run) return { label: "No SLA", tone: "default" };
  if (run.status === "COMPLETED") {
    return run.breached
      ? { label: "Completed (breached)", tone: "danger" }
      : { label: "Completed", tone: "success" };
  }
  if (run.breached || (run.remaining_seconds !== null && run.remaining_seconds < 0)) {
    return { label: "Breached", tone: "danger" };
  }
  const remaining = run.remaining_seconds !== null ? formatDuration(run.remaining_seconds) : "—";
  if (run.status === "PAUSED") return { label: `Paused · ${remaining} left`, tone: "info" };
  const atRisk = run.elapsed_fraction !== null && run.elapsed_fraction >= 0.8;
  return { label: `${remaining} remaining`, tone: atRisk ? "warning" : "success" };
}

interface TicketAssignmentsCardProps {
  ticketId: string;
  // Bumped by the parent after any ticket-level action (close/reopen/
  // transfer/status) so this card re-reads the fresh assignment state.
  refreshToken?: number;
  onChanged?: () => void;
}

type ModalState =
  | { kind: "add" }
  | { kind: "remove"; assignment: TicketAssignmentItem }
  | null;

export function TicketAssignmentsCard({ ticketId, refreshToken, onChanged }: TicketAssignmentsCardProps) {
  const { currentUser } = useAuthContext();
  const { allCategories } = useWorkflowContext();
  const [state, setState] = useState<TicketAssignmentsResponse | null>(null);
  const [modal, setModal] = useState<ModalState>(null);
  const [candidates, setCandidates] = useState<AssignableAgentsResponse | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [primaryChoice, setPrimaryChoice] = useState<string>("");
  const [newPrimaryId, setNewPrimaryId] = useState<string>("");
  const [categoryToAdd, setCategoryToAdd] = useState<string>("");

  const permissions = currentUser?.permissions ?? [];
  const isSupervisor = !!currentUser && SUPERVISOR_ROLES.has(currentUser.role);
  const canAssign = permissions.includes("ticket:assign");
  const canReassign = isSupervisor || permissions.includes("ticket:transfer");
  const canChangeCategory = permissions.includes("ticket:change_category");
  const canEditOthersStatus = isSupervisor || permissions.includes("ticket:editother_ticket");

  const load = useApiAction(getTicketAssignments);
  const assignAction = useApiAction(assignTicketUsers, { successMessage: "Users assigned." });
  const updateAction = useApiAction(updateTicketAssignment, { successMessage: "Assignment updated." });
  const removeAction = useApiAction(removeTicketAssignment, { successMessage: "User unassigned." });
  const addCategoryAction = useApiAction(addTicketCategory, { successMessage: "Category added." });
  const removeCategoryAction = useApiAction(removeTicketCategory, { successMessage: "Category removed." });
  const candidatesAction = useApiAction(getTransferCandidates);

  const refresh = useCallback(async () => {
    const result = await load.run(ticketId);
    if (result) setState(result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshToken]);

  const applyResult = (result: TicketAssignmentsResponse | null) => {
    if (!result) return false;
    setState(result);
    onChanged?.();
    return true;
  };

  const isClosed = state?.is_closed ?? false;
  const assignments = state?.assignments ?? [];
  const primary = assignments.find((a) => a.is_primary) ?? null;
  const assignedIds = useMemo(() => new Set(assignments.map((a) => a.user_id)), [assignments]);

  const candidateGroups = useMemo(() => {
    const groups: Record<string, SelectableUser[]> = {};
    const roleOrder: string[] = [];
    const push = (role: string, user: { user_id: string; name: string; employee_number?: string | null }) => {
      if (assignedIds.has(user.user_id)) return;
      if (!groups[role]) {
        groups[role] = [];
        roleOrder.push(role);
      }
      if (!groups[role].some((u) => u.user_id === user.user_id)) {
        groups[role].push({ user_id: user.user_id, name: user.name, email: user.employee_number ?? "" });
      }
    };
    if (candidates?.me) push("Me", candidates.me);
    for (const group of candidates?.groups ?? []) {
      for (const user of group.users) push(group.role, user);
    }
    return { groups, roleOrder };
  }, [candidates, assignedIds]);

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const role of candidateGroups.roleOrder) {
      for (const user of candidateGroups.groups[role]) map.set(user.user_id, user.name);
    }
    return map;
  }, [candidateGroups]);

  const openAdd = async () => {
    setSelectedIds([]);
    setPrimaryChoice("");
    setModal({ kind: "add" });
    const result = await candidatesAction.run(ticketId);
    if (result) setCandidates(result);
  };

  const submitAdd = async () => {
    const primaryUserId = primaryChoice || (primary ? null : selectedIds[0] ?? null);
    const ok = applyResult(await assignAction.run(ticketId, selectedIds, primaryUserId));
    if (ok) setModal(null);
  };

  const submitRemove = async () => {
    if (modal?.kind !== "remove") return;
    const ok = applyResult(
      await removeAction.run(ticketId, modal.assignment.assignment_id, newPrimaryId || null)
    );
    if (ok) setModal(null);
  };

  const changeStatus = async (assignment: TicketAssignmentItem, status: TicketStatus) => {
    applyResult(await updateAction.run(ticketId, assignment.assignment_id, { status }));
  };

  const makePrimary = async (assignment: TicketAssignmentItem) => {
    applyResult(await updateAction.run(ticketId, assignment.assignment_id, { is_primary: true }));
  };

  const addCategory = async () => {
    if (!categoryToAdd) return;
    if (applyResult(await addCategoryAction.run(ticketId, categoryToAdd))) setCategoryToAdd("");
  };

  const ticketCategories = state?.categories ?? [];
  const availableCategories = (allCategories ?? []).filter(
    (c) => !ticketCategories.some((tc) => tc.category_id === c.category_id)
  );
  const removeTarget = modal?.kind === "remove" ? modal.assignment : null;
  const removingPrimaryWithOthers =
    !!removeTarget && removeTarget.is_primary && assignments.length > 1;

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          <Users size={14} /> Assignments
        </span>
      }
      actions={
        !isClosed && canAssign ? (
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} onClick={openAdd}>
            Add Users
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-4 p-5" data-testid="ticket-assignments-card">
        {isClosed && (
          <div className="flex items-center gap-2 rounded-md2 border border-border bg-canvas/60 px-3 py-2 text-xs text-slate-700">
            <Lock size={13} className="text-muted" />
            Ticket is closed — every assignment is closed and every assignee SLA has stopped.
          </div>
        )}

        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
            Assigned Users
          </p>
          {assignments.length === 0 ? (
            <p className="text-sm text-muted">Unassigned</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border rounded-md2 border border-border">
              {assignments.map((assignment) => {
                const sla = describeAssignmentSla(assignment.resolution_sla);
                const isMine = assignment.user_id === currentUser?.user_id;
                const canChangeThisStatus = !isClosed && (isMine || canEditOthersStatus);
                return (
                  <li
                    key={assignment.assignment_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5"
                    data-testid={`assignment-row-${assignment.user_id}`}
                  >
                    <span className="min-w-[8rem] flex-1 truncate text-sm font-medium text-slate-800">
                      {assignment.user_name ?? assignment.user_id}
                      {isMine && <span className="ml-1 text-xs text-muted">(you)</span>}
                    </span>
                    <Badge tone={assignment.is_primary ? "accent" : "default"} icon={assignment.is_primary ? <Crown size={11} /> : undefined}>
                      {assignment.is_primary ? "Primary" : "Secondary"}
                    </Badge>
                    {canChangeThisStatus ? (
                      <select
                        aria-label={`Status for ${assignment.user_name ?? "assignee"}`}
                        className="rounded-md2 border border-border bg-surface px-2 py-1 text-xs"
                        value={assignment.status}
                        disabled={updateAction.isLoading}
                        onChange={(e) => void changeStatus(assignment, e.target.value as TicketStatus)}
                      >
                        {!ASSIGNMENT_STATUSES.includes(assignment.status) && (
                          <option value={assignment.status}>{STATUS_LABEL[assignment.status]}</option>
                        )}
                        {ASSIGNMENT_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {STATUS_LABEL[s]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Badge tone={statusTone[assignment.status]} dot>
                        {STATUS_LABEL[assignment.status]}
                      </Badge>
                    )}
                    <Badge tone={sla.tone}>{sla.label}</Badge>
                    {!isClosed && canReassign && !assignment.is_primary && (
                      <Button size="sm" variant="ghost" onClick={() => void makePrimary(assignment)}>
                        Make Primary
                      </Button>
                    )}
                    {!isClosed && canReassign && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<UserMinus size={13} />}
                        aria-label={`Remove ${assignment.user_name ?? "assignee"}`}
                        onClick={() => {
                          setNewPrimaryId("");
                          setModal({ kind: "remove", assignment });
                        }}
                      >
                        Remove
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
            Categories
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {ticketCategories.map((category) => (
              <span
                key={category.category_id}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-canvas px-2.5 py-0.5 text-xs text-slate-800"
                data-testid={`category-chip-${category.category_name}`}
              >
                <Tag size={11} className="text-muted" />
                {category.category_name}
                {category.is_primary && <span className="text-[10px] text-muted">(primary)</span>}
                {!isClosed && canChangeCategory && ticketCategories.length > 1 && (
                  <button
                    type="button"
                    aria-label={`Remove category ${category.category_name}`}
                    className="ml-0.5 rounded-full p-0.5 text-muted hover:bg-surfaceHover hover:text-slate-900"
                    onClick={async () =>
                      applyResult(await removeCategoryAction.run(ticketId, category.category_id))
                    }
                  >
                    <X size={11} />
                  </button>
                )}
              </span>
            ))}
            {!isClosed && canChangeCategory && availableCategories.length > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <select
                  aria-label="Category to add"
                  className="rounded-md2 border border-border bg-surface px-2 py-1 text-xs"
                  value={categoryToAdd}
                  onChange={(e) => setCategoryToAdd(e.target.value)}
                >
                  <option value="">+ Add category…</option>
                  {availableCategories.map((c) => (
                    <option key={c.category_id} value={c.category_id}>
                      {c.category_name}
                    </option>
                  ))}
                </select>
                {categoryToAdd && (
                  <Button size="sm" variant="secondary" isLoading={addCategoryAction.isLoading} onClick={addCategory}>
                    Add
                  </Button>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      <Modal
        open={modal?.kind === "add"}
        title="Assign Users"
        onClose={() => setModal(null)}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={assignAction.isLoading}
            disabled={selectedIds.length === 0}
            onClick={submitAdd}
          >
            Assign {selectedIds.length > 0 ? `(${selectedIds.length})` : ""}
          </Button>
        }
      >
        <div className="flex flex-col gap-4">
          <UserMultiSelect
            label="Users"
            hint="Every selected user gets their own status and their own resolution SLA."
            groups={candidateGroups.groups}
            roleOrder={candidateGroups.roleOrder}
            selectedIds={selectedIds}
            onChange={setSelectedIds}
          />
          <SelectInput
            label="Primary"
            hint={
              primary
                ? `Current primary: ${primary.user_name ?? "—"}. The primary is accountable for escalation.`
                : "This ticket has no primary yet — the first selected user becomes primary unless you choose."
            }
            value={primaryChoice}
            onChange={(e) => setPrimaryChoice(e.target.value)}
          >
            <option value="">{primary ? "Keep current primary" : "First selected user"}</option>
            {selectedIds.map((id) => (
              <option key={id} value={id}>
                {nameById.get(id) ?? id}
              </option>
            ))}
          </SelectInput>
        </div>
      </Modal>

      <Modal
        open={modal?.kind === "remove"}
        title="Remove Assignee"
        onClose={() => setModal(null)}
        footer={
          <Button
            variant="primary"
            size="sm"
            isLoading={removeAction.isLoading}
            disabled={removingPrimaryWithOthers && !newPrimaryId}
            onClick={submitRemove}
          >
            Remove
          </Button>
        }
      >
        <div className="flex flex-col gap-3 text-sm text-slate-700">
          <p>
            Remove <strong>{removeTarget?.user_name ?? "this user"}</strong> from the ticket? Their
            assignment history and SLA history are kept.
          </p>
          {removingPrimaryWithOthers && (
            <SelectInput
              label="New primary"
              hint="The primary can't be removed without choosing who becomes primary."
              value={newPrimaryId}
              onChange={(e) => setNewPrimaryId(e.target.value)}
            >
              <option value="">Select…</option>
              {assignments
                .filter((a) => a.assignment_id !== removeTarget?.assignment_id)
                .map((a) => (
                  <option key={a.assignment_id} value={a.assignment_id}>
                    {a.user_name ?? a.user_id}
                  </option>
                ))}
            </SelectInput>
          )}
        </div>
      </Modal>
    </Card>
  );
}
