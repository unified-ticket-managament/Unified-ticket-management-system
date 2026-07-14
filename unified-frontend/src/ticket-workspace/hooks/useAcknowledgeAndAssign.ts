import { useState } from "react";
import { acknowledgeTicketEscalation, getAcknowledgeCandidates } from "@tw/api/sla";
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

/**
 * Shared by SlaCard.tsx (the ticket detail page's Escalation section)
 * and TicketsListPage.tsx (the Escalated tab's row action) — both
 * places an escalation can be acknowledged. Acknowledging always also
 * settles who owns the ticket going forward (self or another agent),
 * never a bare "OK, seen it" click — see each call site's own comment
 * for the product reasoning.
 *
 * Three pre-existing backend calls cover every case, no backend change
 * needed: if the chosen agent already IS the assigned agent, the
 * ticket itself isn't changing, so only the plain acknowledge endpoint
 * fires; if the ticket is unclaimed and the chosen agent is the
 * caller, claiming records a CLAIM (not a TRANSFER) event, matching
 * TicketActions.tsx's own convention, but claim_ticket doesn't
 * auto-acknowledge (only transfer_agent does), so an explicit
 * acknowledge call follows it; every other case (assigning to someone
 * else, or reassigning away from the current agent to anyone
 * including the caller) goes through transfer_agent, which
 * acknowledges automatically as a side effect
 * (EscalationService.acknowledge_via_assignment) — never fires the
 * plain acknowledge call itself, since that would 400 on an
 * already-acknowledged escalation.
 */
export function useAcknowledgeAndAssign() {
  const { currentUser } = useAuthContext();
  const [isOpen, setIsOpen] = useState(false);
  const [target, setTarget] = useState<TargetTicket | null>(null);
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
  const isSubmitting = isAcknowledging || isClaiming || isTransferring;

  function open(ticket: TargetTicket) {
    setTarget(ticket);
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
  // group's users) — used only for the confirm()/name-lookup logic
  // below, which doesn't care which role group an id came from. The
  // modal itself renders `groups` as separate <optgroup>s, plus "Myself"
  // on its own.
  const allUsers: AssignableUserSummary[] = currentUser
    ? [
        { user_id: currentUser.user_id, name: currentUser.name },
        ...groups.flatMap((g) => g.users).filter((u) => u.user_id !== currentUser.user_id),
      ]
    : groups.flatMap((g) => g.users);

  async function confirm(): Promise<ConfirmResult> {
    if (!target || !selectedAgentId) return { success: false };

    let success = false;
    if (selectedAgentId === target.currentAgentId) {
      success = Boolean(await runAcknowledge(target.ticketId));
    } else if (!target.currentAgentId && selectedAgentId === currentUser?.user_id) {
      const claimed = await runClaim(target.ticketId);
      if (claimed) success = Boolean(await runAcknowledge(target.ticketId));
    } else {
      const transferred = await runTransfer(target.ticketId, { new_agent_id: selectedAgentId });
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
    // "Myself" is a real, explicit option here (unlike TicketActions'
    // own Transfer picker, which excludes the caller in favor of a
    // separate Claim button) — acknowledging an escalation is exactly
    // the moment a supervisor decides whether to take it on personally
    // or delegate it.
    me: currentUser ? { user_id: currentUser.user_id, name: currentUser.name } : null,
    groups,
    selectedAgentId,
    setSelectedAgentId,
    confirm,
    isSubmitting,
  };
}
