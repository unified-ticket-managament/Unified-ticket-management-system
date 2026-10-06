import { useEffect, useRef } from "react";

import { subscribeMailEvents } from "@/lib/mail-events";

// How long to wait after the LAST event before refetching. A poll can
// ingest a dozen messages within one tick, and each produces an event; this
// turns that burst into a single refetch instead of one per message.
export const LIVE_MAIL_DEBOUNCE_MS = 400;

// Runs `onRefresh` (a silent, targeted refetch of the Mail lists) whenever
// the backend says mail arrived — without a manual Refresh, a page reload
// or any periodic polling.
//
// - Coalescing: any number of events within the debounce window cause ONE
//   refetch; events arriving while a refetch is running cause exactly one
//   more afterwards (so nothing is missed, and requests never pile up).
// - Hidden tab: the refetch is deferred until the tab is visible again, so
//   a background tab does no work and the user sees fresh mail on return.
// - A single window listener for the life of the component: the latest
//   `onRefresh` is read through a ref, so re-renders never add listeners.
// - Failures are swallowed: this is best-effort on top of the existing
//   Inbox; the Refresh button and normal navigation remain the fallback.
export function useLiveMailRefresh(
  onRefresh: () => Promise<unknown> | void,
  debounceMs: number = LIVE_MAIL_DEBOUNCE_MS
): void {
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;

  useEffect(() => {
    let pending = false;
    let running = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    async function flush() {
      if (disposed || !pending) return;
      if (typeof document !== "undefined" && document.hidden) return; // resumes on visibilitychange
      if (running) return; // the finally block below re-runs once
      pending = false;
      running = true;
      try {
        await refreshRef.current();
      } catch {
        // best-effort: never surface a failure from the live path
      } finally {
        running = false;
        if (pending && !disposed) void flush();
      }
    }

    function schedule() {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        void flush();
      }, debounceMs);
    }

    const unsubscribe = subscribeMailEvents(() => {
      pending = true;
      schedule();
    });

    function onVisibility() {
      if (!document.hidden && pending) void flush();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      unsubscribe();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [debounceMs]);
}
