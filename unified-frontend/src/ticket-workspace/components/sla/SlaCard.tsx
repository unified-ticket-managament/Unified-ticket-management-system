"use client";

import { useState } from "react";
import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { useAuthContext } from "@tw/context/AuthContext";
import { useTicketSla } from "@tw/hooks/useTicketSla";
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
}: {
  ticketId: string;
  ticketPriority: TicketPriority;
}) {
  const { currentUser } = useAuthContext();
  const {
    resolution,
    targetMinutes,
    elapsedFraction,
    remainingSeconds,
    tier,
    isLoading,
    pause,
    resume,
    isPausing,
    isResuming,
  } = useTicketSla(ticketId, ticketPriority);

  const [showPauseInput, setShowPauseInput] = useState(false);
  const [pauseReason, setPauseReason] = useState("");

  const canOverride = currentUser?.role ? RESOLUTION_OVERRIDE_ROLES.has(currentUser.role) : false;

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
    <Card
      title="Resolution SLA"
      eyebrow="Service level"
      actions={
        canOverride && resolution.status === "PAUSED" ? (
          <Button size="sm" variant="secondary" isLoading={isResuming} onClick={() => resume()}>
            Resume
          </Button>
        ) : canOverride && resolution.status === "RUNNING" && !showPauseInput ? (
          <Button size="sm" variant="secondary" onClick={() => setShowPauseInput(true)}>
            Pause
          </Button>
        ) : undefined
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

        {showPauseInput && (
          <div className="flex flex-col gap-2 rounded-md2 border border-border bg-canvas p-3">
            <label className="text-xs font-medium text-slate-700">Reason for manual pause</label>
            <input
              autoFocus
              value={pauseReason}
              onChange={(e) => setPauseReason(e.target.value)}
              placeholder="e.g. Waiting on internal escalation"
              className="rounded-md2 border border-border bg-surface px-2.5 py-1.5 text-xs outline-none focus:ring-2 focus:ring-accent/30"
            />
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setShowPauseInput(false);
                  setPauseReason("");
                }}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                isLoading={isPausing}
                disabled={!pauseReason.trim()}
                onClick={async () => {
                  const result = await pause(pauseReason.trim());
                  if (result) {
                    setShowPauseInput(false);
                    setPauseReason("");
                  }
                }}
              >
                Confirm Pause
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
