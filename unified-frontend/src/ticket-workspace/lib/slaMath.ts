// ==========================================================
// slaMath
//
// Pure, dependency-free helpers for turning an SLA clock's raw fields
// (due_at, status, paused_at) into what the UI actually needs: a tier
// (healthy/at_risk/breached/escalated), a fraction for a progress bar,
// and human-readable remaining/elapsed strings that tick live between
// polls.
//
// Deliberately mirrors the backend's own thresholds/formula
// (unified-backend/app/ticketing/services/sla_service.py's
// compute_elapsed_fraction, and sla_sweep_service.py's THRESHOLDS) so
// the frontend's tier classification agrees with what the sweep would
// eventually report — but with one intentional correction: the
// backend's own `elapsed_fraction` keeps climbing against wall-clock
// time even while a clock is PAUSED (due_at is frozen but the fraction
// isn't recomputed relative to that freeze). This file's
// computeElapsedFraction is PAUSED-aware and freezes the fraction at
// the moment of pausing instead, so the UI doesn't show a paused
// ticket's bar creeping toward 100% for no reason.
// ==========================================================

export type SlaTier = "healthy" | "at_risk" | "breached" | "escalated";

const AT_RISK_THRESHOLD = 0.8;
const BREACHED_THRESHOLD = 1.0;
const ESCALATED_THRESHOLD = 1.5;

export function classifyTier(fraction: number): SlaTier {
  if (fraction >= ESCALATED_THRESHOLD) return "escalated";
  if (fraction >= BREACHED_THRESHOLD) return "breached";
  if (fraction >= AT_RISK_THRESHOLD) return "at_risk";
  return "healthy";
}

export const SLA_TIER_LABEL: Record<SlaTier, string> = {
  healthy: "Healthy",
  at_risk: "At Risk",
  breached: "Breached",
  escalated: "Escalated",
};

interface ElapsedFractionInput {
  dueAt: string;
  targetMinutes: number;
  now: Date;
  // Pass these two for a Resolution clock so a PAUSED clock's fraction
  // freezes instead of climbing — omit (or leave both null) for a
  // First Response clock, which has no pause concept at all.
  status?: "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED";
  pausedAt?: string | null;
}

export function computeElapsedFraction({
  dueAt,
  targetMinutes,
  now,
  status,
  pausedAt,
}: ElapsedFractionInput): number {
  if (targetMinutes <= 0) return 1;

  // The one deliberate deviation from the backend: while PAUSED, judge
  // progress as of the moment it was paused, not "right now" — due_at
  // is frozen server-side too, so this keeps the bar/countdown honest
  // about the fact that nothing is actually being consumed right now.
  const effectiveNow = status === "PAUSED" && pausedAt ? new Date(pausedAt) : now;

  const targetSeconds = targetMinutes * 60;
  const remainingSeconds = (new Date(dueAt).getTime() - effectiveNow.getTime()) / 1000;
  return 1 - remainingSeconds / targetSeconds;
}

export function computeRemainingSeconds({
  dueAt,
  now,
  status,
  pausedAt,
}: Pick<ElapsedFractionInput, "dueAt" | "now" | "status" | "pausedAt">): number {
  const effectiveNow = status === "PAUSED" && pausedAt ? new Date(pausedAt) : now;
  return (new Date(dueAt).getTime() - effectiveNow.getTime()) / 1000;
}

// "2m 14s" / "1h 3m" / "3d 2h" — short, dashboard-friendly, no
// seconds precision once it's over an hour (nobody needs
// "3h 2m 41s" ticking on a card).
export function formatDurationShort(totalSeconds: number): string {
  const abs = Math.abs(Math.round(totalSeconds));
  const days = Math.floor(abs / 86400);
  const hours = Math.floor((abs % 86400) / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const seconds = abs % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function formatRemainingLabel(remainingSeconds: number): string {
  if (remainingSeconds >= 0) return `${formatDurationShort(remainingSeconds)} remaining`;
  return `Overdue by ${formatDurationShort(remainingSeconds)}`;
}

// First Response has no dedicated API — this recomputes the exact
// same due_at formula the backend uses when it starts the clock
// (app/ticketing/services/sla_service.py's start_first_response_clock:
// due_at = started_at + first_response_target_minutes), from data
// that's already available via existing, already-verified endpoints
// (the inbox listing's `received_at`, and GET /sla/policies for the
// MEDIUM target — First Response always prices against MEDIUM
// regardless of the eventual ticket's priority, a backend design
// choice, not an approximation this file is introducing).
export function computeFirstResponseDueAt(receivedAt: string, targetMinutes: number): string {
  return new Date(new Date(receivedAt).getTime() + targetMinutes * 60_000).toISOString();
}
