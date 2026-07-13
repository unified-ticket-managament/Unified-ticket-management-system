import { useEffect, useState } from "react";
import { getTicketSla, listSlaPolicies } from "@tw/api/sla";
import { classifyTier, computeElapsedFraction } from "@tw/lib/slaMath";
import type { SLAPolicyResponse, TicketResponse } from "@tw/types";

export interface DashboardSlaCounts {
  running: number;
  paused: number;
  atRisk: number;
  breached: number;
  escalated: number;
  completed: number;
}

const EMPTY_COUNTS: DashboardSlaCounts = {
  running: 0,
  paused: 0,
  atRisk: 0,
  breached: 0,
  escalated: 0,
  completed: 0,
};

const REFRESH_INTERVAL_MS = 15_000;

// No aggregate endpoint exists for this (only the per-ticket
// GET /tickets/{id}/sla) — this calls it once per ticket and
// aggregates client-side. Acceptable at demo scale (a handful of
// tickets); a real aggregate endpoint would be needed before this
// pattern should ever run against a production-sized ticket list —
// see the performance review earlier this session for exactly why an
// N-calls-per-page-load pattern like this doesn't scale.
export function useDashboardSlaCounts(tickets: TicketResponse[]) {
  const [counts, setCounts] = useState<DashboardSlaCounts>(EMPTY_COUNTS);
  const [isLoading, setIsLoading] = useState(true);
  const [policies, setPolicies] = useState<SLAPolicyResponse[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listSlaPolicies()
      .then((data) => {
        if (!cancelled) setPolicies(data);
      })
      .catch(() => {
        // Without policies, tier classification can't happen — the
        // load effect below just leaves running/paused/completed
        // countable (status alone) and skips tier-splitting.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (tickets.length === 0) {
      setCounts(EMPTY_COUNTS);
      setIsLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setIsLoading(true);
      const results = await Promise.all(
        tickets.map((t) => getTicketSla(t.ticket_id).catch(() => null))
      );
      if (cancelled) return;

      const next = { ...EMPTY_COUNTS };
      const now = new Date();

      results.forEach((sla, index) => {
        const resolution = sla?.resolution;
        if (!resolution) return;

        if (resolution.status === "COMPLETED") {
          next.completed += 1;
          return;
        }
        if (resolution.status === "PAUSED") {
          next.paused += 1;
          return;
        }
        if (resolution.status === "RUNNING") {
          next.running += 1;
          const targetMinutes = policies?.find(
            (p) => p.priority === tickets[index].current_priority
          )?.resolution_target_minutes;
          if (targetMinutes != null) {
            const fraction = computeElapsedFraction({
              dueAt: resolution.due_at,
              targetMinutes,
              now,
              status: resolution.status,
              pausedAt: resolution.paused_at,
            });
            const tier = classifyTier(fraction);
            if (tier === "at_risk") next.atRisk += 1;
            else if (tier === "breached") next.breached += 1;
            else if (tier === "escalated") next.escalated += 1;
          }
        }
      });

      setCounts(next);
      setIsLoading(false);
    }

    load();
    const intervalId = window.setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickets, policies]);

  return { counts, isLoading };
}
