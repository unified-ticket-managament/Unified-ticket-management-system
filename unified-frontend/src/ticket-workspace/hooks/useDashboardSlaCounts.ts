import { useEffect, useState } from "react";
import { getSlaOverviewCounts } from "@tw/api/ticket";

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

// One grouped backend query (GET /tickets/sla-overview-counts) under
// the same visibility scoping as every other ticket-list endpoint.
// This used to fetch every visible ticket unbounded (listTickets())
// and then call GET /tickets/{id}/sla once per ticket to classify it
// client-side — an N+1 round-trip pattern (1 + up to hundreds of
// individual SLA lookups) that was both why this tile was slow to
// resolve and why it sat on its "…" loading placeholder for as long as
// it did. See TicketRepository.sla_overview_counts for the SQL side.
export function useDashboardSlaCounts() {
  const [counts, setCounts] = useState<DashboardSlaCounts>(EMPTY_COUNTS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      try {
        const data = await getSlaOverviewCounts(controller.signal);
        if (cancelled) return;
        setCounts({
          running: data.running,
          paused: data.paused,
          atRisk: data.at_risk,
          breached: data.breached,
          escalated: data.escalated,
          completed: data.completed,
        });
      } catch {
        // Silent on a transient failure — same convention as the rest
        // of this app's polling: the tile just keeps showing its last
        // known values instead of an error toast on top of whatever
        // the page's own main load() already surfaces.
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    const intervalId = window.setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, []);

  return { counts, isLoading };
}
