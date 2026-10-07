"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { MailReminder } from "@tw/api/mailReminders";
import { RemindMeDialog } from "@tw/components/mail/RemindMeDialog";
import { useToast } from "@tw/context/ToastContext";
import { useMailReminders } from "@tw/hooks/useMailReminders";
import { formatReminderTime, type ReminderDialogMode } from "@tw/lib/reminderPresets";

// One provider owns the user's reminder state and the single
// RemindMeDialog, so every entry point (row ⋮ menu, right-click menu,
// reading-pane toolbar, the "due" banner) just calls into this context
// instead of threading props through MessageList / MessageDetailsView.
// Same shape as MailBulkContext: consumers get `null` outside a provider
// and simply don't render reminder UI, so any screen that mounts
// MessageDetailsView without a provider keeps working unchanged.

export interface MailReminderContextValue {
  // The reminder (ACTIVE preferred, else FIRED) for a thread-root id.
  reminderFor: (interactionId: string) => MailReminder | undefined;
  // Opens the dialog to create a reminder for this email.
  remind: (interactionId: string) => void;
  // Opens the dialog to change an ACTIVE reminder's time.
  edit: (reminder: MailReminder) => void;
  // Opens the dialog to snooze a (usually FIRED) reminder.
  snooze: (reminder: MailReminder) => void;
  // Removes an ACTIVE/FIRED reminder (server-side: CANCELED).
  remove: (reminder: MailReminder) => Promise<void>;
  // Acknowledges a FIRED reminder.
  dismiss: (reminder: MailReminder) => Promise<void>;
}

const MailReminderContext = createContext<MailReminderContextValue | null>(null);

export function useMailReminder(): MailReminderContextValue | null {
  return useContext(MailReminderContext);
}

type DialogState =
  | { open: false }
  | {
      open: true;
      mode: ReminderDialogMode;
      interactionId: string;
      reminder?: MailReminder;
    };

export function MailReminderProvider({ children }: { children: ReactNode }) {
  const api = useMailReminders();
  const { pushToast } = useToast();
  const [dialog, setDialog] = useState<DialogState>({ open: false });

  const { byInteractionId, create, update, cancel, snooze, dismiss } = api;

  const reminderFor = useCallback(
    (interactionId: string) => byInteractionId.get(interactionId),
    [byInteractionId]
  );

  const remind = useCallback(
    (interactionId: string) =>
      setDialog({ open: true, mode: "create", interactionId }),
    []
  );
  const edit = useCallback(
    (reminder: MailReminder) =>
      setDialog({
        open: true,
        mode: "edit",
        interactionId: reminder.interaction_id,
        reminder,
      }),
    []
  );
  const openSnooze = useCallback(
    (reminder: MailReminder) =>
      setDialog({
        open: true,
        mode: "snooze",
        interactionId: reminder.interaction_id,
        reminder,
      }),
    []
  );

  const remove = useCallback(
    async (reminder: MailReminder) => {
      try {
        await cancel(reminder.reminder_id);
        pushToast("Reminder removed", "success");
      } catch (err) {
        pushToast(err instanceof Error ? err.message : "Couldn't remove the reminder.", "error");
      }
    },
    [cancel, pushToast]
  );

  const dismissReminder = useCallback(
    async (reminder: MailReminder) => {
      try {
        await dismiss(reminder.reminder_id);
        pushToast("Reminder dismissed", "success");
      } catch (err) {
        pushToast(err instanceof Error ? err.message : "Couldn't dismiss the reminder.", "error");
      }
    },
    [dismiss, pushToast]
  );

  const handleSubmit = useCallback(
    async (date: Date) => {
      if (!dialog.open) return;
      // Errors are NOT caught here: RemindMeDialog shows the message
      // inline and stays open so the user's choice isn't lost.
      if (dialog.mode === "create") {
        const created = await create(dialog.interactionId, date);
        pushToast(`Reminder set for ${formatReminderTime(date)}`, "success", {
          action: {
            label: "Undo",
            onClick: () => {
              void cancel(created.reminder_id).catch(() =>
                pushToast("Couldn't undo the reminder.", "error")
              );
            },
          },
        });
      } else if (dialog.mode === "edit" && dialog.reminder) {
        await update(dialog.reminder.reminder_id, date);
        pushToast(`Reminder moved to ${formatReminderTime(date)}`, "success");
      } else if (dialog.mode === "snooze" && dialog.reminder) {
        await snooze(dialog.reminder.reminder_id, { remind_at: date.toISOString() });
        pushToast(`Snoozed until ${formatReminderTime(date)}`, "success");
      }
    },
    [dialog, create, update, snooze, cancel, pushToast]
  );

  const value = useMemo<MailReminderContextValue>(
    () => ({
      reminderFor,
      remind,
      edit,
      snooze: openSnooze,
      remove,
      dismiss: dismissReminder,
    }),
    [reminderFor, remind, edit, openSnooze, remove, dismissReminder]
  );

  return (
    <MailReminderContext.Provider value={value}>
      {children}
      <RemindMeDialog
        open={dialog.open}
        onOpenChange={(open) => {
          if (!open) setDialog({ open: false });
        }}
        mode={dialog.open ? dialog.mode : "create"}
        initialDate={
          dialog.open && dialog.mode === "edit" && dialog.reminder
            ? new Date(dialog.reminder.remind_at)
            : null
        }
        onSubmit={handleSubmit}
      />
    </MailReminderContext.Provider>
  );
}
