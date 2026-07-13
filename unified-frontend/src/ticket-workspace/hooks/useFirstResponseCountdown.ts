import { useEffect, useState } from "react";
import { listSlaPolicies } from "@tw/api/sla";
import {
  classifyTier,
  computeElapsedFraction,
  computeFirstResponseDueAt,
  computeRemainingSeconds,
  type SlaTier,
} from "@tw/lib/slaMath";
import type { SLAPolicyResponse } from "@tw/types";

const TICK_INTERVAL_MS = 1_000;

// First Response has no dedicated read endpoint (confirmed against
// app/ticketing/api/sla.py — only ticket-scoped Resolution reads and
// policy CRUD exist). This recomputes the clock client-side from data
// two already-existing, already-verified endpoints provide: the inbox
// item's own `received_at`, and GET /sla/policies for MEDIUM's target
// (First Response always prices against MEDIUM regardless of the
// eventual ticket's priority — a backend design choice this mirrors,
// not an approximation of it).
//
// `enabled` should be false once the item is no longer pending (e.g.
// already turned into a ticket or archived) — there's no "is this
// clock still running" signal available client-side, so the caller is
// responsible for only rendering/enabling this while an item is still
// showing up as a pending inbox row.
export function useFirstResponseCountdown(receivedAt: string | undefined, enabled: boolean) {
  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    listSlaPolicies()
      .then((data) => {
        if (!cancelled) setPolicies(data);
      })
      .catch(() => {
        // No policy data → countdown just doesn't render (handled by
        // the caller checking targetMinutes/dueAt for null).
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    const tickId = window.setInterval(() => setNow(new Date()), TICK_INTERVAL_MS);
    return () => window.clearInterval(tickId);
  }, [enabled]);

  const targetMinutes = policies?.find((p) => p.priority === "MEDIUM")?.first_response_target_minutes ?? null;

  const dueAt =
    enabled && receivedAt && targetMinutes != null
      ? computeFirstResponseDueAt(receivedAt, targetMinutes)
      : null;

  const elapsedFraction =
    dueAt && targetMinutes != null ? computeElapsedFraction({ dueAt, targetMinutes, now }) : null;

  const remainingSeconds = dueAt ? computeRemainingSeconds({ dueAt, now }) : null;

  const tier: SlaTier | null = elapsedFraction != null ? classifyTier(elapsedFraction) : null;

  return { dueAt, targetMinutes, elapsedFraction, remainingSeconds, tier };
}
