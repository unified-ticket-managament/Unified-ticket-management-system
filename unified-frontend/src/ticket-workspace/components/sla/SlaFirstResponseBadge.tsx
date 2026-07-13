"use client";

import { useFirstResponseCountdown } from "@tw/hooks/useFirstResponseCountdown";
import { formatRemainingLabel } from "@tw/lib/slaMath";
import { SlaBadge } from "@tw/components/sla/SlaBadge";

// Drop-in badge for a still-pending inbox item — live First Response
// countdown computed client-side (see useFirstResponseCountdown for
// why: no dedicated read endpoint exists). `enabled` should reflect
// whether this item is still actually pending triage; the caller
// (MessageDetailsView) already knows this from the same `email`
// object used to render the rest of the header.
export function SlaFirstResponseBadge({
  receivedAt,
  enabled,
}: {
  receivedAt: string;
  enabled: boolean;
}) {
  const { remainingSeconds, tier } = useFirstResponseCountdown(receivedAt, enabled);

  if (!enabled || !tier || remainingSeconds == null) return null;

  return (
    <div className="flex items-center gap-1.5">
      <SlaBadge tier={tier} />
      <span className="text-[11px] text-muted-foreground">
        First Response: {formatRemainingLabel(remainingSeconds)}
      </span>
    </div>
  );
}
