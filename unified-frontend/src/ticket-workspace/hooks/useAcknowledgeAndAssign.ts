import { useState } from "react";
import {
  acknowledgeTicketEscalation,
  confirmEscalationAssignment,
  getAcknowledgeCandidates,
} from "@tw/api/sla";
import { claimTicket, transferTicketAgent } from "@tw/api/ticket";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useAuthContext } from "@tw/context/AuthContext";
import type { AssignableGroup, AssignableUserSummary } from "@tw/types";

interface TargetTicket {
  ticketId: string;
  ticketType: string;
  currentAgentId: string | null;
}

interface ConfirmResult {
  success: boolean;
  agentId?: string;
  agentName?: string;
}

export type AcknowledgeAssignStep = "acknowledge" | "assign";

/**
 * Shared by SlaCard.tsx (the ticket detail page's Escalation section)
 * and TicketsListPage.tsx (the Escalated tab's row action) — both
 * places an escalation can be acknowledged. Both call sites only ever
 * open this for an escalation that's still ACTIVE (not yet
 * acknowledged) — see each call site's own canAcknowledge/
 * canAcknowledgeRow gate — so this always starts at the "acknowledge"
 * step.
 *
 * Two explicit, sequential steps, not one fused action: the ticket's
 * escalation must actually be acknowledged before assignment becomes
 * possible at all, matching the required workflow ("first see an
 * Acknowledge button — until acknowledged, cannot assign"). Step 1
 * calls the plain acknowledge endpoint alone; only once that succeeds
 * does step 2 (assign to self/another agent) become reachable.
 *
 * Step 2 covers every case across four backend calls: if the chosen
 * agent already IS the assigned agent, confirmEscalationAssignment is
 * called explicitly — this is the one branch that never reaches
 * claim_ticket/transfer_agent, so without it the Resolution SLA and
 * escalation-handling SLA would never start at all for a "keep the
 * current owner" confirmation (acknowledging in step 1 alone
 * deliberately does NOT start either clock — see
 * EscalationService.acknowledge's own docstring); if the ticket is
 * unclaimed and the chosen agent is the caller, claim_ticket records a
 * CLAIM (not a TRANSFER) event, matching TicketActions.tsx's own
 * convention; every other case (assigning to someone else, or
 * reassigning away from the current agent) goes through
 * transfer_agent. claim_ticket and transfer_agent both also call
 * EscalationService.acknowledge_via_assignment, which is where the
 * Resolution SLA/handling SLA actually start for those two branches —
 * idempotent whether or not step 1's Acknowledge click already ran.
 */
export function useAcknowledgeAndAssign() {
  const { currentUser } = useAuthContext();
  const [isOpen, setIsOpen] = useState(false);
  const [target, setTarget] = useState<TargetTicket | null>(null);
  const [step, setStep] = useState<AcknowledgeAssignStep>("acknowledge");
  // Role-scoped groups from the backend (see
  // EscalationService.get_acknowledge_candidates) — who appears here
  // differs by the caller's own role, e.g. a Site Lead sees Team
  // Lead + Account Manager options, a Team Lead sees Staff.
  const [groups, setGroups] = useState<AssignableGroup[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");

  const { run: runAcknowledge, isLoading: isAcknowledging } = useApiAction(
    acknowledgeTicketEscalation
  );
  const { run: runClaim, isLoading: isClaiming } = useApiAction(claimTicket);
  const { run: runTransfer, isLoading: isTransferring } = useApiAction(transferTicketAgent);
  const { run: runConfirmAssignment, isLoading: isConfirmingAssignment } = useApiAction(
    confirmEscalationAssignment
  );
  const isSubmitting =
    isAcknowledging || isClaiming || isTransferring || isConfirmingAssignment;

  function open(ticket: TargetTicket) {
    setTarget(ticket);
    setStep("acknowledge");
    setSelectedAgentId(ticket.currentAgentId ?? currentUser?.user_id ?? "");
    setIsOpen(true);
    getAcknowledgeCandidates(ticket.ticketId)
      .then((res) => setGroups(res.groups))
      .catch(() => setGroups([]));
  }

  function close() {
    setIsOpen(false);
  }

  // Flat, id-keyed view of every selectable person (self + every
  // group's users) — used only for the confirmAssignment()/name-lookup
  // logic below, which doesn't care which role group an id came from.
  // The modal itself renders `groups` as separate <optgroup>s, plus
  // "Myself" on its own.
  const allUsers: AssignableUserSummary[] = currentUser
    ? [
        { user_id: currentUser.user_id, name: currentUser.name },
        ...groups.flatMap((g) => g.users).filter((u) => u.user_id !== currentUser.user_id),
      ]
    : groups.flatMap((g) => g.users);

  // Step 1 — acknowledge alone, no assignment decision yet. Advances
  // to step 2 on success; leaves the modal open (on "acknowledge") on
  // failure so the user can retry, same convention confirmAssignment
  // below already follows.
  async function confirmAcknowledge(): Promise<boolean> {
    if (!target) return false;
    const result = await runAcknowledge(target.ticketId);
    if (result) {
      setStep("assign");
      return true;
    }
    return false;
  }

  // Step 2 — only reachable after step 1 succeeded. Settles who owns
  // the ticket going forward.
  async function confirmAssignment(): Promise<ConfirmResult> {
    if (!target || !selectedAgentId) return { success: false };

    let success = false;
    if (selectedAgentId === target.currentAgentId) {
      // No reassignment requested — this never reaches claim_ticket
      // or transfer_agent, so it's the one branch that must call the
      // backend explicitly to actually start the Resolution SLA/
      // handling SLA (acknowledging in step 1 alone never does).
      success = Boolean(await runConfirmAssignment(target.ticketId));
    } else if (!target.currentAgentId && selectedAgentId === currentUser?.user_id) {
      success = Boolean(await runClaim(target.ticketId));
    } else {
      const transferred = await runTransfer(target.ticketId, {
        new_agent_id: selectedAgentId,
        // This flow has no free-text reason input of its own (see this
        // hook's own docstring — assigning here is a side effect of
        // acknowledging an escalation, not the dedicated Transfer
        // Ticket action), so a fixed, descriptive reason satisfies the
        // now-required field without adding a UI prompt to this modal.
        reason: "Reassigned via Acknowledge & Assign (escalation)",
      });
      success = Boolean(transferred);
    }

    if (success) {
      setIsOpen(false);
      // The real display name, not the dropdown's "Myself (...)"
      // label — callers patch their own ticket row/state with this.
      const agentName =
        selectedAgentId === currentUser?.user_id
          ? currentUser.name
          : allUsers.find((u) => u.user_id === selectedAgentId)?.name;
      return { success: true, agentId: selectedAgentId, agentName };
    }
    // Failed calls already surfaced their own error toast via
    // useApiAction — leave the modal open so the user can retry or
    // pick a different agent instead of it silently vanishing.
    return { success: false };
  }

  return {
    isOpen,
    open,
    close,
    step,
    // "Myself" is a real, explicit option here (unlike TicketActions'
    // own Transfer picker, which excludes the caller in favor of a
    // separate Claim button) — assigning an already-acknowledged
    // escalation is exactly the moment a supervisor decides whether to
    // take it on personally or delegate it.
    me: currentUser ? { user_id: currentUser.user_id, name: currentUser.name } : null,
    groups,
    selectedAgentId,
    setSelectedAgentId,
    confirmAcknowledge,
    confirmAssignment,
    isAcknowledging,
    isSubmitting,
  };
}
