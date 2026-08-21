import { useCallback, useEffect, useRef, useState } from "react";
import { getSlaOverviewCounts } from "@tw/api/ticket";

// No `breached` field — Resolution SLA no longer has a separate
// BREACHED tier; `escalated` now covers everything at or past 100%
// elapsed, not just past the old 150% cutoff (see
// TicketRepository.sla_overview_counts).
export interface DashboardSlaCounts {
  running: number;
  paused: number;
  atRisk: number;
  escalated: number;
  completed: number;
}

const EMPTY_COUNTS: DashboardSlaCounts = {
  running: 0,
  paused: 0,
  atRisk: 0,
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
// `clientCompanyId` (optional) narrows the tile row to one client,
// within whatever the caller's own role scope already allows — a
// change to it re-fires the poll immediately (via `load`'s own
// dependency below), same as a mount or a manual refresh().
export function useDashboardSlaCounts(clientCompanyId?: string) {
  const [counts, setCounts] = useState<DashboardSlaCounts>(EMPTY_COUNTS);
  const [isLoading, setIsLoading] = useState(true);
  const isUnmountedRef = useRef(false);
  // A fresh controller per call (aborting whatever the previous call
  // was still waiting on first) so a manual refresh() and the
  // periodic poll below can never race each other's response.
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const data = await getSlaOverviewCounts(clientCompanyId, controller.signal);
      if (isUnmountedRef.current) return;
      setCounts({
        running: data.running,
        paused: data.paused,
        atRisk: data.at_risk,
        escalated: data.escalated,
        completed: data.completed,
      });
    } catch {
      // Silent on a transient failure (including a superseded
      // request's own cancellation) — same convention as the rest of
      // this app's polling: the tile just keeps showing its last
      // known values instead of an error toast on top of whatever the
      // page's own main load() already surfaces.
    } finally {
      if (!isUnmountedRef.current) setIsLoading(false);
    }
  }, [clientCompanyId]);

  useEffect(() => {
    isUnmountedRef.current = false;
    load();
    const intervalId = window.setInterval(load, REFRESH_INTERVAL_MS);
    return () => {
      isUnmountedRef.current = true;
      controllerRef.current?.abort();
      window.clearInterval(intervalId);
    };
  }, [load]);

  return { counts, isLoading, refresh: load };
}
