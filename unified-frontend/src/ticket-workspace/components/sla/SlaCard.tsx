"use client";

import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { useAuthContext } from "@tw/context/AuthContext";
import { useTicketSla } from "@tw/hooks/useTicketSla";
import { useAcknowledgeAndAssign } from "@tw/hooks/useAcknowledgeAndAssign";
import { AcknowledgeAssignModal } from "@tw/components/sla/AcknowledgeAssignModal";
import { formatDateTime } from "@tw/lib/format";
import { formatDurationShort, formatRemainingLabel } from "@tw/lib/slaMath";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import { SlaProgressBar } from "@tw/components/sla/SlaProgressBar";
import type { TicketPriority } from "@tw/types";

// Deliberately NOT reusing lib/role-access.ts's SUPERVISOR_ROLE_NAMES
// constant (only [Site Lead, Super Admin]) to gate the pause/resume
// buttons — that constant is already documented (this app's own
// CLAUDE.md) as not matching the real backend gate, which is
// access_control.py's SUPERVISOR_ROLE_NAMES = {Team Lead, Account
// Manager, Site Lead, Super Admin}. Using the narrower frontend
// constant here would hide this button from Team Lead/Account
// Manager even though the backend lets them pause/resume — verified
// directly against the API earlier (Team Lead: 200, Staff: 403).
const RESOLUTION_OVERRIDE_ROLES = new Set(["Team Lead", "Account Manager", "Site Lead", "Super Admin"]);

export function SlaCard({
  ticketId,
  ticketPriority,
  ticketType,
  currentAgentId,
  onActionComplete,
}: {
  ticketId: string;
  ticketPriority: TicketPriority;
  ticketType: string;
  currentAgentId: string | null;
  onActionComplete: () => void;
}) {
  const { currentUser } = useAuthContext();
  const {
    resolution,
    escalation,
    escalationHandlingSla,
    policy,
    targetMinutes,
    elapsedFraction,
    remainingSeconds,
    tier,
    isLoading,
    resume,
    isResuming,
    escalate,
    isEscalating,
    refetch,
  } = useTicketSla(ticketId, ticketPriority);

  const acknowledgeAndAssign = useAcknowledgeAndAssign();

  const canOverride = currentUser?.role ? RESOLUTION_OVERRIDE_ROLES.has(currentUser.role) : false;

  const canEscalate =
    !!currentUser?.permissions.includes("ticket:escalate") &&
    !escalation &&
    resolution?.status !== "COMPLETED";

  // Strictly owner_ids membership — no Site Lead/Super Admin bypass.
  // The backend (EscalationService.acknowledge/confirm_assignment)
  // dropped its own "global overseer" exception for the same reason:
  // escalation should progress one level at a time, and a Site
  // Lead/Super Admin only becomes a real owner once the chain
  // actually reaches SITE_LEAD.
  const canAcknowledge =
    !!currentUser &&
    escalation?.status === "ACTIVE" &&
    escalation.owner_ids.includes(currentUser.user_id);

  async function handleAcknowledgeStep() {
    const acknowledged = await acknowledgeAndAssign.confirmAcknowledge();
    if (acknowledged) {
      // Acknowledging alone already changed escalation.status and
      // started the escalation-handling SLA — pull fresh state
      // immediately rather than waiting for the assignment step too.
      await refetch();
      onActionComplete();
    }
  }

  async function handleAssignStep() {
    const result = await acknowledgeAndAssign.confirmAssignment();
    if (result.success) {
      // Transfer/claim changed something this hook's own SLA state
      // doesn't already reflect — pull it fresh, then let the parent
      // re-fetch the ticket itself (agent_id/agent_name).
      await refetch();
      onActionComplete();
    }
  }

  // escalate() (from useTicketSla) only refreshes this card's own SLA
  // state — it has no way to know about onActionComplete, since that
  // prop only exists for the acknowledge+assign flow above. But
  // escalating now also permanently bumps the ticket's own
  // current_priority to CRITICAL (see EscalationService.
  // _bump_priority_to_critical on the backend) — a ticket-level field
  // that lives in the parent's activeTicket state, not this hook's own
  // sla state, so the parent must re-fetch the ticket too or its
  // header/properties card keeps showing the pre-escalation priority.
  async function handleEscalate() {
    const result = await escalate();
    if (result) onActionComplete();
  }

  if (isLoading) {
    return (
      <Card title="Resolution SLA" eyebrow="Service level">
        <SkeletonRows rows={3} />
      </Card>
    );
  }

  if (!resolution) {
    return (
      <Card title="Resolution SLA" eyebrow="Service level">
        <p className="text-xs text-muted">No resolution clock on this ticket yet.</p>
      </Card>
    );
  }

  const badgeTier = resolution.status === "RUNNING" ? tier : null;

  return (
    <>
    <Card
      title="Resolution SLA"
      eyebrow="Service level"
      actions={
        <div className="flex items-center gap-2">
          {canOverride && resolution.status === "PAUSED" && (
            <Button size="sm" variant="secondary" isLoading={isResuming} onClick={() => resume()}>
              Resume
            </Button>
          )}
          {canEscalate && (
            <Button size="sm" variant="secondary" isLoading={isEscalating} onClick={handleEscalate}>
              Escalate
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted">Status</span>
          {badgeTier ? (
            <SlaBadge tier={badgeTier} />
          ) : (
            <span className="text-xs font-semibold text-slate-700">{resolution.status}</span>
          )}
        </div>

        {resolution.status === "RUNNING" && elapsedFraction != null && (
          <div className="flex flex-col gap-1.5">
            <SlaProgressBar tier={tier ?? "healthy"} fraction={elapsedFraction} />
            {remainingSeconds != null && (
              <p className="text-xs text-muted">{formatRemainingLabel(remainingSeconds)}</p>
            )}
          </div>
        )}

        {resolution.status === "PAUSED" && resolution.paused_at && (
          <p className="rounded-md2 bg-warning/10 px-3 py-2 text-xs text-warning">
            Paused since {formatDateTime(resolution.paused_at)} — the clock is frozen, not
            counting down.
          </p>
        )}

        <dl className="grid grid-cols-2 gap-x-3 gap-y-3 text-xs">
          <div>
            <dt className="text-muted">Target</dt>
            <dd className="font-medium text-slate-800">
              {targetMinutes != null ? formatDurationShort(targetMinutes * 60) : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Due</dt>
            <dd className="font-medium text-slate-800">{formatDateTime(resolution.due_at)}</dd>
          </div>
          <div>
            <dt className="text-muted">Time paused (total)</dt>
            <dd className="font-medium text-slate-800">
              {formatDurationShort(resolution.total_paused_seconds)}
            </dd>
          </div>
          <div>
            <dt className="text-muted">Completed</dt>
            <dd className="font-medium text-slate-800">
              {resolution.completed_at ? formatDateTime(resolution.completed_at) : "—"}
            </dd>
          </div>
        </dl>

        {/*
          Read-only config summary for THIS ticket's own priority only —
          sourced from the same one-time listSlaPolicies() fetch
          useTicketSla already does (filtered to ticketPriority, no
          extra request), never the full Critical/High/Medium/Low
          matrix (that lives only in Settings -> SLA Timing Matrix,
          Super Admin only). Values here are the configured policy,
          not this ticket's own live/running state, so they don't
          change if the matrix is edited after this ticket started.
        */}
        {policy && (
          <div className="flex flex-col gap-2 rounded-md2 border border-border bg-canvas p-3">
            <span className="text-xs font-semibold text-slate-700">
              SLA Configuration — {ticketPriority}
            </span>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-3 text-xs">
              <div>
                <dt className="text-muted">Escalation Ack Window</dt>
                <dd className="font-medium text-slate-800">
                  {formatDurationShort(policy.escalation_ack_target_minutes * 60)}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Handling SLA</dt>
                <dd className="font-medium text-slate-800">
                  {policy.handling_sla_percentage}% of Resolution SLA (
                  {formatDurationShort(
                    Math.round(
                      policy.resolution_target_minutes * 60 * (policy.handling_sla_percentage / 100)
                    )
                  )}
                  )
                </dd>
              </div>
            </dl>
          </div>
        )}

        {/*
          Internal escalation — deliberately its own section, visually
          separate from the Resolution SLA fields above, and never a
          second countdown/timer: escalating never restarts or
          recalculates the Resolution SLA (started_at/due_at above are
          exactly what they'd be if this section didn't exist at all).
          This only shows who currently owns following up and when
          they must acknowledge.
        */}
        {escalation && (
          <div className="flex flex-col gap-3 rounded-md2 border border-border bg-canvas p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-700">Escalation</span>
              <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[11px] font-medium text-warning">
                {escalation.status === "ACTIVE"
                  ? "Awaiting acknowledgment"
                  : escalation.status === "ACKNOWLEDGED"
                    ? "Acknowledged"
                    : "Closed"}
              </span>
            </div>

            <dl className="grid grid-cols-2 gap-x-3 gap-y-3 text-xs">
              <div>
                <dt className="text-muted">Current Level</dt>
                <dd className="font-medium text-slate-800">
                  {escalation.level.replace("_", " ")}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Escalation Owner</dt>
                <dd className="font-medium text-slate-800">
                  {escalation.owner_names.length > 0 ? escalation.owner_names.join(", ") : "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Acknowledgment Due</dt>
                <dd className="font-medium text-slate-800">
                  {formatDateTime(escalation.ack_due_at)}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Overdue Duration</dt>
                <dd className="font-medium text-slate-800">
                  {escalation.overdue_seconds > 0
                    ? formatDurationShort(escalation.overdue_seconds)
                    : "Not overdue"}
                </dd>
              </div>
            </dl>

            {canAcknowledge && (
              <Button
                size="sm"
                variant="primary"
                onClick={() =>
                  acknowledgeAndAssign.open({ ticketId, ticketType, currentAgentId })
                }
              >
                Acknowledge &amp; Assign
              </Button>
            )}
          </div>
        )}

        {/*
          Escalation Handling SLA — a second, independent clock from
          the Resolution SLA above. It never means the original SLA
          restarted: the Resolution SLA's own started_at/due_at/status
          fields (shown above, unchanged) still reflect exactly what
          they'd be if this ticket had never escalated at all. This
          only shows how long the current escalation owner has to
          actually resolve the ticket, target = 25% of the original
          Resolution SLA's configured target duration.
        */}
        {escalationHandlingSla && (
          <div className="flex flex-col gap-3 rounded-md2 border border-border bg-canvas p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-700">Escalation Handling SLA</span>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  escalationHandlingSla.breached_at
                    ? "bg-danger/10 text-danger"
                    : escalationHandlingSla.status === "COMPLETED"
                      ? "bg-success/10 text-success"
                      : "bg-info/10 text-info"
                }`}
              >
                {escalationHandlingSla.breached_at
                  ? "Breached"
                  : escalationHandlingSla.status === "COMPLETED"
                    ? "Completed"
                    : "Running"}
              </span>
            </div>

            <dl className="grid grid-cols-2 gap-x-3 gap-y-3 text-xs">
              <div>
                <dt className="text-muted">Target</dt>
                <dd className="font-medium text-slate-800">
                  {formatDurationShort(escalationHandlingSla.target_seconds)}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Due</dt>
                <dd className="font-medium text-slate-800">
                  {formatDateTime(escalationHandlingSla.due_at)}
                </dd>
              </div>
              <div>
                <dt className="text-muted">
                  {escalationHandlingSla.status === "COMPLETED" ? "Completed" : "Remaining"}
                </dt>
                <dd className="font-medium text-slate-800">
                  {escalationHandlingSla.status === "COMPLETED"
                    ? escalationHandlingSla.completed_at
                      ? formatDateTime(escalationHandlingSla.completed_at)
                      : "—"
                    : formatRemainingLabel(escalationHandlingSla.remaining_seconds)}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Breached</dt>
                <dd className="font-medium text-slate-800">
                  {escalationHandlingSla.breached_at
                    ? formatDateTime(escalationHandlingSla.breached_at)
                    : "Not breached"}
                </dd>
              </div>
            </dl>
          </div>
        )}
      </div>
    </Card>

    <AcknowledgeAssignModal
      open={acknowledgeAndAssign.isOpen}
      onClose={acknowledgeAndAssign.close}
      step={acknowledgeAndAssign.step}
      me={acknowledgeAndAssign.me}
      groups={acknowledgeAndAssign.groups}
      selectedAgentId={acknowledgeAndAssign.selectedAgentId}
      onSelectAgent={acknowledgeAndAssign.setSelectedAgentId}
      onAcknowledge={handleAcknowledgeStep}
      onConfirmAssignment={handleAssignStep}
      isAcknowledging={acknowledgeAndAssign.isAcknowledging}
      isSubmitting={acknowledgeAndAssign.isSubmitting}
    />
    </>
  );
}
