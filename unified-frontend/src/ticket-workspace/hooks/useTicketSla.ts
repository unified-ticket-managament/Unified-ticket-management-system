import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import {
  escalateTicket,
  getTicketSla,
  listSlaPolicies,
  resumeTicketSla,
} from "@tw/api/sla";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useToast } from "@tw/context/ToastContext";
import { classifyTier, computeElapsedFraction, computeRemainingSeconds, type SlaTier } from "@tw/lib/slaMath";
import type { SLAPolicyResponse, TicketPriority, TicketSLAResponse } from "@tw/types";

const POLL_INTERVAL_MS = 8_000;
const TICK_INTERVAL_MS = 1_000;

// Server-confirmed state (polled) plus a live-ticking "now" so the
// countdown/progress bar move smoothly between polls instead of
// jumping once every 8 seconds.
export function useTicketSla(ticketId: string | undefined, ticketPriority: TicketPriority | undefined) {
  const { pushToast } = useToast();
  const [sla, setSla] = useState<TicketSLAResponse | null>(null);
  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [isLoading, setIsLoading] = useState(true);
  const lastTierRef = useRef<SlaTier | null>(null);
  const slaAbortRef = useRef<AbortController | null>(null);

  const { run: runResume, isLoading: isResuming } = useApiAction(resumeTicketSla);
  const { run: runEscalate, isLoading: isEscalating } = useApiAction(escalateTicket);

  const fetchSla = useCallback(async () => {
    if (!ticketId) return;
    // Cancel any still-in-flight poll/refetch for the previous ticket
    // (or a superseded tick) at the network layer, rather than letting
    // it complete and race a newer response into setSla.
    slaAbortRef.current?.abort();
    const controller = new AbortController();
    slaAbortRef.current = controller;
    try {
      const data = await getTicketSla(ticketId, controller.signal);
      setSla(data);
    } catch (error) {
      if (axios.isCancel(error)) return;
      // Same silent-on-poll-failure convention as the notification
      // bell — a transient failure just means this tick shows
      // slightly stale data, not an error banner.
    } finally {
      if (slaAbortRef.current === controller) setIsLoading(false);
    }
  }, [ticketId]);

  // Policies rarely change — fetched once per mount, not on the
  // 8-second poll interval.
  useEffect(() => {
    const controller = new AbortController();
    listSlaPolicies(controller.signal)
      .then((data) => setPolicies(data))
      .catch((error) => {
        if (axios.isCancel(error)) return;
        // No policy data just means target minutes stay unknown and
        // the tier can't be computed — SlaCard handles that as an
        // empty state rather than crashing.
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    lastTierRef.current = null;
    setSla(null);
    setIsLoading(true);
    fetchSla();
    const pollId = window.setInterval(fetchSla, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(pollId);
      slaAbortRef.current?.abort();
    };
  }, [fetchSla]);

  useEffect(() => {
    const tickId = window.setInterval(() => setNow(new Date()), TICK_INTERVAL_MS);
    return () => window.clearInterval(tickId);
  }, []);

  // The one policy row applicable to this ticket's own priority — not
  // the full matrix. `policies` itself is fetched once per mount (see
  // above) and never re-fetched per ticket; this is a pure lookup, no
  // extra network call.
  const policy = policies?.find((p) => p.priority === ticketPriority) ?? null;
  const targetMinutes = policy?.resolution_target_minutes ?? null;

  const resolution = sla?.resolution ?? null;

  const elapsedFraction =
    resolution && targetMinutes != null
      ? computeElapsedFraction({
          dueAt: resolution.due_at,
          targetMinutes,
          now,
          status: resolution.status,
          pausedAt: resolution.paused_at,
        })
      : null;

  const remainingSeconds = resolution
    ? computeRemainingSeconds({
        dueAt: resolution.due_at,
        now,
        status: resolution.status,
        pausedAt: resolution.paused_at,
      })
    : null;

  const tier: SlaTier | null =
    resolution?.status === "RUNNING" && elapsedFraction != null ? classifyTier(elapsedFraction) : null;

  // Instant client-side feedback the moment a tier crosses a
  // threshold — doesn't wait for the backend sweep (which, locally,
  // only runs when manually triggered). Only fires on a genuine
  // increase observed while mounted, never on first load, so opening
  // an already-at-risk ticket doesn't toast immediately.
  useEffect(() => {
    if (!tier) return;
    const previous = lastTierRef.current;
    lastTierRef.current = tier;
    if (previous === null || previous === tier) return;

    const order: SlaTier[] = ["healthy", "at_risk", "breached", "escalated"];
    if (order.indexOf(tier) <= order.indexOf(previous)) return;

    if (tier === "at_risk") {
      pushToast("Resolution SLA is now At Risk (80% of target elapsed).", "info");
    } else if (tier === "breached") {
      pushToast("Resolution SLA has been Breached.", "error");
    } else if (tier === "escalated") {
      pushToast("Resolution SLA has Escalated (150% of target elapsed).", "error");
    }
  }, [tier, pushToast]);

  const resume = useCallback(async () => {
    if (!ticketId) return;
    const result = await runResume(ticketId);
    if (result) await fetchSla();
    return result;
  }, [ticketId, runResume, fetchSla]);

  const escalate = useCallback(async () => {
    if (!ticketId) return;
    const result = await runEscalate(ticketId);
    if (result) await fetchSla();
    return result;
  }, [ticketId, runEscalate, fetchSla]);

  return {
    sla,
    resolution,
    escalation: sla?.escalation ?? null,
    escalationHandlingSla: sla?.escalation_handling_sla ?? null,
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
    refetch: fetchSla,
  };
}
