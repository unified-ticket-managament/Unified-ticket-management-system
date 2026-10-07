import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelReminder,
  createReminder,
  dismissReminder,
  getReminders,
  snoozeReminder,
  updateReminder,
  type MailReminder,
  type SnoozeTarget,
} from "@tw/api/mailReminders";

// Keeps the signed-in user's open reminders (ACTIVE = waiting, FIRED =
// due and not yet dismissed) in one place, keyed by thread-root
// interaction id, so the list rows, menus and the reading pane can all
// ask "does this email have a reminder?" without each fetching.
//
// Deliberately independent of useMailInbox: reminder state never touches
// the inbox rows, so none of the existing mail state handling changes.
//
// Freshness: a reminder becomes FIRED server-side without any request
// from this tab, so the list is refetched when the tab regains focus /
// becomes visible and on a slow interval. (A due reminder also arrives
// as a MAIL_REMINDER_DUE notification in the bell, which deep-links to
// the email — opening it mounts the reading pane, which reads this map.)

export const REMINDER_REFRESH_INTERVAL_MS = 60_000;

export interface MailRemindersApi {
  reminders: MailReminder[];
  byInteractionId: ReadonlyMap<string, MailReminder>;
  isLoaded: boolean;
  refresh: () => Promise<void>;
  create: (interactionId: string, remindAt: Date) => Promise<MailReminder>;
  update: (reminderId: string, remindAt: Date) => Promise<MailReminder>;
  cancel: (reminderId: string) => Promise<void>;
  snooze: (reminderId: string, target: SnoozeTarget) => Promise<MailReminder>;
  dismiss: (reminderId: string) => Promise<MailReminder>;
}

export function useMailReminders(): MailRemindersApi {
  const [reminders, setReminders] = useState<MailReminder[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);
  const mountedRef = useRef(true);
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    try {
      const [active, fired] = await Promise.all([
        getReminders({ status: "ACTIVE" }),
        getReminders({ status: "FIRED" }),
      ]);
      // Ignore a response that a newer refresh has already superseded.
      if (!mountedRef.current || requestId !== requestRef.current) return;
      setReminders([...active, ...fired]);
      setIsLoaded(true);
    } catch {
      // Reminders are an enhancement: a failed background refresh must
      // never disturb mail. Keep what we have and try again next tick.
      if (mountedRef.current && requestId === requestRef.current) setIsLoaded(true);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();

    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const onFocus = () => void refresh();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onFocus);
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, REMINDER_REFRESH_INTERVAL_MS);

    return () => {
      mountedRef.current = false;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onFocus);
      window.clearInterval(timer);
    };
  }, [refresh]);

  // An ACTIVE reminder wins over a FIRED one for the same thread (the
  // user set a new one after the old one fired).
  const byInteractionId = useMemo(() => {
    const map = new Map<string, MailReminder>();
    for (const r of reminders) {
      const existing = map.get(r.interaction_id);
      if (!existing || (existing.status !== "ACTIVE" && r.status === "ACTIVE")) {
        map.set(r.interaction_id, r);
      }
    }
    return map;
  }, [reminders]);

  // Every mutation goes to the server first and then re-reads the
  // authoritative list, so the UI never shows a state the server
  // rejected. Errors propagate to the caller (dialog / toast).
  const create = useCallback(
    async (interactionId: string, remindAt: Date) => {
      const r = await createReminder(interactionId, remindAt);
      await refresh();
      return r;
    },
    [refresh]
  );
  const update = useCallback(
    async (reminderId: string, remindAt: Date) => {
      const r = await updateReminder(reminderId, remindAt);
      await refresh();
      return r;
    },
    [refresh]
  );
  const cancel = useCallback(
    async (reminderId: string) => {
      await cancelReminder(reminderId);
      await refresh();
    },
    [refresh]
  );
  const snooze = useCallback(
    async (reminderId: string, target: SnoozeTarget) => {
      const r = await snoozeReminder(reminderId, target);
      await refresh();
      return r;
    },
    [refresh]
  );
  const dismiss = useCallback(
    async (reminderId: string) => {
      const r = await dismissReminder(reminderId);
      await refresh();
      return r;
    },
    [refresh]
  );

  return {
    reminders,
    byInteractionId,
    isLoaded,
    refresh,
    create,
    update,
    cancel,
    snooze,
    dismiss,
  };
}
