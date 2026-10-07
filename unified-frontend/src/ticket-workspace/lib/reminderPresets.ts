// Pure date/time helpers for the "Remind me" dialog. Everything takes
// `now` as a parameter (never reads the clock itself) so the presets and
// validation are deterministic under test. All "wall clock" decisions
// (tomorrow 9 AM, next Monday…) use the browser's local timezone; the
// result is an absolute Date, which the API client sends as a UTC
// instant — the server never needs to know the user's timezone.

export type ReminderPresetId =
  | "in1Hour"
  | "in3Hours"
  | "laterToday"
  | "tomorrow"
  | "nextWeek";

export interface ReminderPreset {
  id: ReminderPresetId;
  label: string;
  date: Date;
}

export type ReminderDialogMode = "create" | "edit" | "snooze";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

// The server rejects reminders further out than this; checked here too
// so the user gets an inline message instead of a failed request.
export const MAX_REMINDER_DAYS = 365;

function atLocalTime(base: Date, hours: number, minutes = 0): Date {
  const d = new Date(base);
  d.setHours(hours, minutes, 0, 0);
  return d;
}

function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

export function tomorrowMorning(now: Date): Date {
  return atLocalTime(addDays(now, 1), 9);
}

// Next Monday at 9:00 AM — "next week" even when today is Monday.
export function nextWeekMorning(now: Date): Date {
  const daysUntilMonday = ((8 - now.getDay()) % 7) || 7;
  return atLocalTime(addDays(now, daysUntilMonday), 9);
}

export function buildPresets(
  now: Date,
  mode: ReminderDialogMode = "create"
): ReminderPreset[] {
  const presets: ReminderPreset[] = [];

  if (mode === "snooze") {
    presets.push({ id: "in1Hour", label: "In 1 hour", date: new Date(now.getTime() + HOUR) });
    presets.push({ id: "in3Hours", label: "In 3 hours", date: new Date(now.getTime() + 3 * HOUR) });
  } else {
    // "Later today" = 5:00 PM, only when that is still comfortably ahead
    // (≥ 30 min) and doesn't just duplicate a snooze-style relative option.
    const fivePm = atLocalTime(now, 17);
    if (fivePm.getTime() - now.getTime() >= 30 * MINUTE) {
      presets.push({ id: "laterToday", label: "Later today", date: fivePm });
    } else {
      presets.push({ id: "in3Hours", label: "In 3 hours", date: new Date(now.getTime() + 3 * HOUR) });
    }
  }

  presets.push({ id: "tomorrow", label: "Tomorrow", date: tomorrowMorning(now) });
  presets.push({ id: "nextWeek", label: "Next week", date: nextWeekMorning(now) });
  return presets;
}

export type CustomParseResult =
  | { ok: true; date: Date }
  | { ok: false; error: string };

// `dateStr` is <input type="date"> ("YYYY-MM-DD"), `timeStr` is
// <input type="time"> ("HH:mm"), both in the user's local time.
export function parseCustomDateTime(
  dateStr: string,
  timeStr: string,
  now: Date
): CustomParseResult {
  if (!dateStr || !timeStr) {
    return { ok: false, error: "Choose a date and a time." };
  }
  const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  const tm = /^(\d{2}):(\d{2})$/.exec(timeStr);
  if (!dm || !tm) {
    return { ok: false, error: "Enter a valid date and time." };
  }
  const [y, mo, d] = [Number(dm[1]), Number(dm[2]), Number(dm[3])];
  const [h, mi] = [Number(tm[1]), Number(tm[2])];
  const date = new Date(y, mo - 1, d, h, mi, 0, 0);
  // Rejects 2026-02-31, 25:00 … (Date silently rolls those over).
  if (
    date.getFullYear() !== y ||
    date.getMonth() !== mo - 1 ||
    date.getDate() !== d ||
    date.getHours() !== h ||
    date.getMinutes() !== mi
  ) {
    return { ok: false, error: "Enter a valid date and time." };
  }
  return validateReminderDate(date, now);
}

export function validateReminderDate(date: Date, now: Date): CustomParseResult {
  if (Number.isNaN(date.getTime())) {
    return { ok: false, error: "Enter a valid date and time." };
  }
  if (date.getTime() <= now.getTime()) {
    return { ok: false, error: "Pick a time in the future." };
  }
  if (date.getTime() > now.getTime() + MAX_REMINDER_DAYS * 24 * HOUR) {
    return { ok: false, error: "Reminders can be set up to 1 year ahead." };
  }
  return { ok: true, date };
}

const pad = (n: number) => String(n).padStart(2, "0");

// For pre-filling <input type="date"> / <input type="time"> (local time).
export function toDateInputValue(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
export function toTimeInputValue(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

// "Today 3:00 PM", "Tomorrow 9:00 AM", "Oct 8, 9:00 AM" (+ year when it
// isn't the current year).
export function formatReminderTime(
  value: Date | string,
  now: Date = new Date()
): string {
  const d = typeof value === "string" ? new Date(value) : value;
  const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  const dayDiff = Math.round((startOfDay(d) - startOfDay(now)) / (24 * HOUR));
  if (dayDiff === 0) return `Today ${time}`;
  if (dayDiff === 1) return `Tomorrow ${time}`;
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
  });
  return `${date}, ${time}`;
}
