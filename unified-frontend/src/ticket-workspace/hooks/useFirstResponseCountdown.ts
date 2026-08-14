import { useEffect, useState } from "react";
import { listSlaPolicies } from "@tw/api/sla";
import {
  classifyTier,
  computeElapsedFraction,
  computeFirstResponseDueAt,
  computeRemainingSeconds,
  type SlaTier,
} from "@tw/lib/slaMath";
import type { FirstResponseSLAState, SLAPolicyResponse } from "@tw/types";

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
//
// `firstResponseSla`, when passed, is the real, DB-backed clock state
// (OpenEmailResponse/InboxItem's own `first_response_sla` field) — the
// caller should always pass whatever it has. When present, this hook
// prefers it entirely: a COMPLETED clock renders as completed (no
// ticking countdown, since nothing is actually still elapsing), and a
// still-PENDING clock ticks against its own real `due_at`/
// `elapsed_fraction` instead of a client-guessed one. Only falls back
// to the client-computed estimate below when `firstResponseSla` is
// `undefined` (a caller that hasn't been updated yet) or `null` (no
// clock row exists at all, e.g. data predating this feature).
export function useFirstResponseCountdown(
  receivedAt: string | undefined,
  enabled: boolean,
  firstResponseSla?: FirstResponseSLAState | null
) {
  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);
  const [now, setNow] = useState(() => new Date());

  const hasRealState = firstResponseSla !== undefined && firstResponseSla !== null;
  const completed = hasRealState && firstResponseSla.status === "COMPLETED";
  const usePolicyFallback = enabled && !hasRealState;

  useEffect(() => {
    if (!usePolicyFallback) return;
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
  }, [usePolicyFallback]);

  useEffect(() => {
    if (!enabled || completed) return;
    const tickId = window.setInterval(() => setNow(new Date()), TICK_INTERVAL_MS);
    return () => window.clearInterval(tickId);
  }, [enabled, completed]);

  if (completed) {
    return {
      dueAt: firstResponseSla.due_at,
      targetMinutes: null,
      elapsedFraction: firstResponseSla.elapsed_fraction,
      remainingSeconds: null,
      tier: null as SlaTier | null,
      completed: true,
      completionReason: firstResponseSla.completion_reason,
    };
  }

  if (hasRealState) {
    const dueAt = firstResponseSla.due_at;
    const remainingSeconds = enabled ? computeRemainingSeconds({ dueAt, now }) : null;
    const tier = classifyTier(firstResponseSla.elapsed_fraction);

    return {
      dueAt,
      targetMinutes: null,
      elapsedFraction: firstResponseSla.elapsed_fraction,
      remainingSeconds,
      tier,
      completed: false,
      completionReason: null,
    };
  }

  const targetMinutes = policies?.find((p) => p.priority === "MEDIUM")?.first_response_target_minutes ?? null;

  const dueAt =
    enabled && receivedAt && targetMinutes != null
      ? computeFirstResponseDueAt(receivedAt, targetMinutes)
      : null;

  const elapsedFraction =
    dueAt && targetMinutes != null ? computeElapsedFraction({ dueAt, targetMinutes, now }) : null;

  const remainingSeconds = dueAt ? computeRemainingSeconds({ dueAt, now }) : null;

  const tier: SlaTier | null = elapsedFraction != null ? classifyTier(elapsedFraction) : null;

  return { dueAt, targetMinutes, elapsedFraction, remainingSeconds, tier, completed: false, completionReason: null };
}
