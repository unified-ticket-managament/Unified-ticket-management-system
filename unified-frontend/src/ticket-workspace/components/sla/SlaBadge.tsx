import { cn } from "@/lib/utils";
import { SLA_TIER_LABEL, type SlaTier } from "@tw/lib/slaMath";

// Deliberately built as a small, self-contained component rather than
// reusing either of this codebase's two existing Badge components
// (@/components/ui/badge's shadcn variant prop, or
// @tw/components/common/Badge's `tone` prop) — pages in this app use
// one or the other inconsistently (Dashboard/TicketDetails use the
// @tw common one, Mail v2 uses shadcn's directly), and neither's
// closed variant/tone union has a 4th tier distinct enough for
// "Escalated" vs "Breached". Raw Tailwind classes against the same
// success/warning/danger color tokens both existing systems already
// share (tailwind.config.ts) keep this visually consistent wherever
// it's dropped in, without picking a side or widening either shared
// component's API for one feature.
const TIER_CLASSES: Record<SlaTier, string> = {
  healthy: "border-success/15 bg-success/10 text-success",
  at_risk: "border-warning/15 bg-warning/10 text-warning",
  breached: "border-danger/15 bg-danger/10 text-danger",
  // Solid fill, not a tint — the one visual step up reserved for the
  // most severe tier, so Breached and Escalated don't read as the
  // same color at a glance.
  escalated: "border-danger bg-danger text-white",
};

const DOT_CLASSES: Record<SlaTier, string> = {
  healthy: "bg-success",
  at_risk: "bg-warning",
  breached: "bg-danger",
  escalated: "bg-white",
};

export function SlaBadge({ tier, className }: { tier: SlaTier; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold leading-none tracking-wide",
        TIER_CLASSES[tier],
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 flex-none rounded-full", DOT_CLASSES[tier])} />
      {SLA_TIER_LABEL[tier]}
    </span>
  );
}
