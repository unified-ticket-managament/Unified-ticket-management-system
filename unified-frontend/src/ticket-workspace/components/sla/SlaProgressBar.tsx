import { cn } from "@/lib/utils";
import type { SlaTier } from "@tw/lib/slaMath";

// Same reasoning as SlaBadge for not reusing @/components/ui/progress
// directly: that component hardcodes its indicator to bg-primary with
// no color-override slot, and this needs to shift color by tier
// (green → yellow → red) — so this mirrors its exact visual language
// (h-2, rounded-full, bg-muted track, 500ms ease-out transition)
// rather than wrapping it.
const FILL_CLASSES: Record<SlaTier, string> = {
  healthy: "bg-success",
  at_risk: "bg-warning",
  breached: "bg-danger",
  escalated: "bg-danger",
};

export function SlaProgressBar({ tier, fraction }: { tier: SlaTier; fraction: number }) {
  const pct = Math.min(100, Math.max(0, fraction * 100));
  return (
    <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full transition-all duration-500 ease-out", FILL_CLASSES[tier])}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
