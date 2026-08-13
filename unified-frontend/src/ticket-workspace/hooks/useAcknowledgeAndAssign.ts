import { useState } from "react";
import { acknowledgeTicketEscalation, getAcknowledgeCandidates } from "@tw/api/sla";
import { useApiAction } from "@tw/hooks/useApiAction";
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
 * places an escalation can be acknowledged.
 *
 * Acknowledging an escalation and deciding who owns the ticket going
 * forward are now a single atomic backend call
 * (InteractionService.acknowledge_and_assign_escalation) — there is no
 * longer a two-step "Acknowledge, then separately Assign" flow, and no
 * way to acknowledge without also picking an assignee. This hook
 * fetches the role-scoped candidate list on open() (same as before),
 * then confirmAssign() submits the chosen assignee_id in one call.
 * Frontend-side, `selectedAgentId` being required before the button
 * enables is a UX guard only — the real enforcement (assignee_id
 * required, must resolve to a valid candidate for the caller's role)
 * happens on the backend, since frontend validation alone was exactly
 * the gap this redesign closes.
 */
export function useAcknowledgeAndAssign() {
  const [isOpen, setIsOpen] = useState(false);
  const [target, setTarget] = useState<TargetTicket | null>(null);
  // Candidate groups AND `me` both come straight from the backend (see
  // EscalationService.get_acknowledge_candidates) — `me` is `null`
  // whenever the caller is a Reporting-Manager-tagged escalation owner
  // (they may Acknowledge + Assign to someone else, never to
  // themselves — root CLAUDE.md's "SLA & Escalation" section, Rule
  // 4/Flow E). This used to be hardcoded from currentUser regardless
  // of what the backend said, which meant "Myself" was always offered
  // and pre-selected even for a caller who isn't allowed to self-assign.
  const [groups, setGroups] = useState<AssignableGroup[]>([]);
  const [me, setMe] = useState<AssignableUserSummary | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");

  const { run: runAcknowledgeAndAssign, isLoading: isSubmitting } = useApiAction(
    acknowledgeTicketEscalation
  );

  function open(ticket: TargetTicket) {
    setTarget(ticket);
    // Never pre-select "myself" here — the candidates response (and
    // its own `me`, possibly null) hasn't loaded yet, and defaulting
    // to currentUser regardless of eligibility is exactly the bug this
    // hook used to have.
    setSelectedAgentId(ticket.currentAgentId ?? "");
    setIsOpen(true);
    getAcknowledgeCandidates(ticket.ticketId)
      .then((res) => {
        setGroups(res.groups);
        setMe(res.me);
      })
      .catch(() => {
        setGroups([]);
        setMe(null);
      });
  }

  function close() {
    setIsOpen(false);
  }

  // Flat, id-keyed view of every selectable person (me, if allowed,
  // plus every group's users) — used only for the name-lookup logic
  // below, which doesn't care which role group an id came from. The
  // modal itself renders `groups` as separate <optgroup>s, plus
  // "Myself" (when `me` is non-null) on its own.
  const allUsers: AssignableUserSummary[] = me
    ? [me, ...groups.flatMap((g) => g.users).filter((u) => u.user_id !== me.user_id)]
    : groups.flatMap((g) => g.users);

  // The one action this hook exposes now — acknowledges the
  // escalation and assigns the ticket to selectedAgentId atomically.
  // Frontend guard: selectedAgentId must be non-empty (the modal's own
  // submit button is also disabled until then — see
  // AcknowledgeAssignModal.tsx), but this check is defense in depth
  // only, not the real enforcement.
  async function confirmAssign(): Promise<ConfirmResult> {
    if (!target || !selectedAgentId) return { success: false };

    const result = await runAcknowledgeAndAssign(target.ticketId, selectedAgentId);
    if (result) {
      setIsOpen(false);
      // The real display name, not the dropdown's "Myself (...)"
      // label — callers patch their own ticket row/state with this.
      const agentName =
        selectedAgentId === me?.user_id
          ? me.name
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
    // separate Claim button) — assigning an already-acknowledged
    // escalation is exactly the moment a supervisor decides whether to
    // take it on personally or delegate it. `null` when the backend
    // says this caller isn't allowed to (see the state comment above).
    me,
    groups,
    selectedAgentId,
    setSelectedAgentId,
    confirmAssign,
    isSubmitting,
  };
}
