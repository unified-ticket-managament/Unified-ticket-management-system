"use client";

import { Bell, BellRing } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useMailReminder } from "@tw/components/mail/MailReminderContext";
import { formatReminderTime } from "@tw/lib/reminderPresets";

// Small presentational pieces for "Remind me". Each reads the shared
// MailReminderContext and renders nothing when there is no provider, so
// they are safe to drop into any mail view.

// Reading-pane toolbar button (next to "Mark as Read/Unread"). With an
// ACTIVE reminder it becomes "Edit reminder" so the same spot manages it.
export function RemindMeToolbarButton({ interactionId }: { interactionId: string }) {
  const reminders = useMailReminder();
  if (!reminders) return null;

  const reminder = reminders.reminderFor(interactionId);
  const isActive = reminder?.status === "ACTIVE";

  return (
    <Button
      size="sm"
      variant="outline"
      className="gap-1.5"
      onClick={() =>
        isActive && reminder ? reminders.edit(reminder) : reminders.remind(interactionId)
      }
    >
      <Bell className="h-3.5 w-3.5" />
      {isActive ? "Edit reminder" : "Remind me"}
    </Button>
  );
}

// Reading-pane header: "🔔 Reminder: Tomorrow 9:00 AM  [Edit] [Remove]" for
// an ACTIVE reminder, and the "Reminder due  [Snooze] [Dismiss]" banner
// for a FIRED one.
export function ReminderStatusBar({ interactionId }: { interactionId: string }) {
  const reminders = useMailReminder();
  if (!reminders) return null;

  const reminder = reminders.reminderFor(interactionId);
  if (!reminder) return null;

  if (reminder.status === "FIRED") {
    return (
      <div
        role="status"
        data-testid="reminder-due-banner"
        className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
      >
        <span className="flex items-center gap-2 font-medium text-foreground">
          <BellRing className="h-4 w-4 text-warning" />
          Reminder due
        </span>
        <span className="flex items-center gap-1.5">
          <Button size="sm" variant="outline" onClick={() => reminders.snooze(reminder)}>
            Snooze
          </Button>
          <Button size="sm" variant="outline" onClick={() => void reminders.dismiss(reminder)}>
            Dismiss
          </Button>
        </span>
      </div>
    );
  }

  if (reminder.status !== "ACTIVE") return null;

  return (
    <div
      data-testid="reminder-chip"
      className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm"
    >
      <Bell className="h-3.5 w-3.5 text-primary" />
      <span>
        Reminder: <span className="font-medium">{formatReminderTime(reminder.remind_at)}</span>
      </span>
      <span className="ml-auto flex items-center gap-1">
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => reminders.edit(reminder)}>
          Edit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2"
          onClick={() => void reminders.remove(reminder)}
        >
          Remove
        </Button>
      </span>
    </div>
  );
}

// Tiny bell shown on a mail-list row that has an ACTIVE (muted) or FIRED
// (highlighted, "due") reminder — sits with the Flag / Pin icons.
export function ReminderRowIcon({ interactionId }: { interactionId: string }) {
  const reminders = useMailReminder();
  const reminder = reminders?.reminderFor(interactionId);
  if (!reminder) return null;

  if (reminder.status === "FIRED") {
    return (
      <BellRing
        aria-label="Reminder due"
        className="h-3.5 w-3.5 flex-none text-warning"
      />
    );
  }
  if (reminder.status !== "ACTIVE") return null;
  return (
    <Bell
      aria-label={`Reminder: ${formatReminderTime(reminder.remind_at)}`}
      className="h-3.5 w-3.5 flex-none text-primary"
    />
  );
}
