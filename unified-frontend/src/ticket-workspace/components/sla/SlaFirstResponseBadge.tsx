"use client";

import { useFirstResponseCountdown } from "@tw/hooks/useFirstResponseCountdown";
import { formatRemainingLabel } from "@tw/lib/slaMath";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import type { FirstResponseSLAState } from "@tw/types";

// Drop-in badge for a still-pending inbox item — First Response
// countdown, preferring the real, DB-backed clock state
// (`firstResponseSla`) when the caller has it, since that's the only
// way to know the clock has already been stopped (e.g. by an OTP
// rule) rather than showing a countdown that ticks forever regardless
// of what actually happened server-side. Falls back to a client-side
// estimate only when `firstResponseSla` is omitted/null — see
// useFirstResponseCountdown's own comment for the full fallback
// behavior. `enabled` should reflect whether this item is still
// actually pending triage; the caller (MessageDetailsView) already
// knows this from the same `email` object used to render the rest of
// the header.
export function SlaFirstResponseBadge({
  receivedAt,
  enabled,
  firstResponseSla,
}: {
  receivedAt: string;
  enabled: boolean;
  firstResponseSla?: FirstResponseSLAState | null;
}) {
  const { remainingSeconds, tier, completed, completionReason } = useFirstResponseCountdown(
    receivedAt,
    enabled,
    firstResponseSla
  );

  if (!enabled) return null;

  if (completed) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-success/15 bg-success/10 px-2.5 py-1 text-[11px] font-semibold leading-none tracking-wide text-success">
          <span className="h-1.5 w-1.5 flex-none rounded-full bg-success" />
          Completed
        </span>
        <span className="text-[11px] text-muted-foreground">
          First Response{completionReason ? ` — ${completionReason}` : ""}
        </span>
      </div>
    );
  }

  if (!tier || remainingSeconds == null) return null;

  return (
    <div className="flex items-center gap-1.5">
      <SlaBadge tier={tier} />
      <span className="text-[11px] text-muted-foreground">
        First Response: {formatRemainingLabel(remainingSeconds)}
      </span>
    </div>
  );
}
