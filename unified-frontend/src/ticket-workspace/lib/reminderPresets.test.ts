import { describe, expect, it } from "vitest";

import {
  MAX_REMINDER_DAYS,
  buildPresets,
  formatReminderTime,
  nextWeekMorning,
  parseCustomDateTime,
  toDateInputValue,
  toTimeInputValue,
  tomorrowMorning,
  validateReminderDate,
} from "@tw/lib/reminderPresets";

// All dates are built from LOCAL components (new Date(y, m, d, h, min)), the
// same way the presets are, so these assertions hold in any timezone.
// Wed 7 Oct 2026, 10:00 local.
const WED_10AM = new Date(2026, 9, 7, 10, 0, 0);
const local = (d: number, h = 9, m = 0, month = 9) => new Date(2026, month, d, h, m, 0);

describe("preset times (R-039)", () => {
  it("offers Later today (5 PM), Tomorrow 9 AM and Next week Monday 9 AM", () => {
    const presets = buildPresets(WED_10AM);

    expect(presets.map((p) => p.id)).toEqual(["laterToday", "tomorrow", "nextWeek"]);
    expect(presets[0].date).toEqual(local(7, 17));
    expect(presets[1].date).toEqual(local(8, 9));
    expect(presets[2].date).toEqual(local(12, 9)); // Monday
  });

  it("swaps 'Later today' for 'In 3 hours' when 5 PM is under 30 minutes away", () => {
    const presets = buildPresets(local(7, 16, 45));

    expect(presets[0].id).toBe("in3Hours");
    expect(presets[0].date).toEqual(local(7, 19, 45));
  });

  it("also swaps it once 5 PM has already passed", () => {
    const presets = buildPresets(local(7, 20, 0));
    expect(presets[0].id).toBe("in3Hours");
    expect(presets[0].date).toEqual(local(7, 23, 0));
  });

  it("every preset is strictly in the future", () => {
    for (const hour of [0, 6, 12, 16, 17, 23]) {
      const now = local(7, hour, 30);
      for (const p of buildPresets(now)) {
        expect(p.date.getTime()).toBeGreaterThan(now.getTime());
      }
    }
  });

  it("'Next week' is the following Monday, never today", () => {
    expect(nextWeekMorning(local(12, 10))).toEqual(local(19, 9)); // Monday -> next Monday
    expect(nextWeekMorning(local(11, 10))).toEqual(local(12, 9)); // Sunday -> tomorrow
    expect(nextWeekMorning(local(10, 10))).toEqual(local(12, 9)); // Saturday
    expect(nextWeekMorning(local(9, 10))).toEqual(local(12, 9)); // Friday
  });

  it("'Tomorrow' crosses month boundaries", () => {
    expect(tomorrowMorning(new Date(2026, 9, 31, 22, 0))).toEqual(new Date(2026, 10, 1, 9, 0));
  });

  it("snooze mode offers relative presets first", () => {
    const presets = buildPresets(WED_10AM, "snooze");

    expect(presets.map((p) => p.id)).toEqual(["in1Hour", "in3Hours", "tomorrow", "nextWeek"]);
    expect(presets[0].date.getTime()).toBe(WED_10AM.getTime() + 60 * 60_000);
    expect(presets[1].date.getTime()).toBe(WED_10AM.getTime() + 3 * 60 * 60_000);
  });
});

describe("custom date & time (R-040)", () => {
  it("accepts a valid future local date and time", () => {
    const r = parseCustomDateTime("2026-10-09", "14:30", WED_10AM);
    expect(r).toEqual({ ok: true, date: local(9, 14, 30) });
  });

  it.each([
    ["", "10:00"],
    ["2026-10-09", ""],
    ["", ""],
  ])("requires both fields (%j, %j)", (d, t) => {
    const r = parseCustomDateTime(d, t, WED_10AM);
    expect(r.ok).toBe(false);
  });

  it.each([
    ["2026-02-31", "10:00"], // rolls over silently in Date()
    ["2026-13-01", "10:00"],
    ["2026-10-09", "25:00"],
    ["2026-10-09", "10:75"],
    ["10/09/2026", "10:00"],
    ["2026-10-09", "10am"],
  ])("rejects an invalid date/time (%j, %j)", (d, t) => {
    const r = parseCustomDateTime(d, t, WED_10AM);
    expect(r).toEqual({ ok: false, error: "Enter a valid date and time." });
  });

  it("rejects the past, and the current minute", () => {
    expect(parseCustomDateTime("2026-10-06", "09:00", WED_10AM)).toEqual({
      ok: false,
      error: "Pick a time in the future.",
    });
    expect(parseCustomDateTime("2026-10-07", "10:00", WED_10AM)).toEqual({
      ok: false,
      error: "Pick a time in the future.",
    });
  });

  it("allows up to one year ahead and rejects beyond it (R-009)", () => {
    const edge = new Date(WED_10AM.getTime() + MAX_REMINDER_DAYS * 24 * 60 * 60_000);
    expect(validateReminderDate(edge, WED_10AM).ok).toBe(true);
    const over = new Date(edge.getTime() + 60_000);
    expect(validateReminderDate(over, WED_10AM)).toEqual({
      ok: false,
      error: "Reminders can be set up to 1 year ahead.",
    });
  });

  it("rejects an invalid Date object", () => {
    expect(validateReminderDate(new Date("nope"), WED_10AM).ok).toBe(false);
  });
});

describe("input value helpers", () => {
  it("formats a Date for <input type=date> / <input type=time> in local time", () => {
    const d = new Date(2026, 0, 5, 7, 4);
    expect(toDateInputValue(d)).toBe("2026-01-05");
    expect(toTimeInputValue(d)).toBe("07:04");
  });

  it("round-trips through parseCustomDateTime", () => {
    const d = local(20, 13, 15);
    const r = parseCustomDateTime(toDateInputValue(d), toTimeInputValue(d), WED_10AM);
    expect(r).toEqual({ ok: true, date: d });
  });
});

describe("formatReminderTime", () => {
  it("says Today / Tomorrow, otherwise a short date", () => {
    expect(formatReminderTime(local(7, 15, 0), WED_10AM)).toMatch(/^Today 3:00\s?PM$/);
    expect(formatReminderTime(local(8, 9, 0), WED_10AM)).toMatch(/^Tomorrow 9:00\s?AM$/);
    expect(formatReminderTime(local(20, 9, 5), WED_10AM)).toMatch(/^Oct 20, 9:05\s?AM$/);
  });

  it("includes the year only when it differs from the current year", () => {
    expect(formatReminderTime(new Date(2027, 0, 4, 9, 0), WED_10AM)).toMatch(/2027/);
    expect(formatReminderTime(local(20, 9, 0), WED_10AM)).not.toMatch(/2026/);
  });

  it("accepts the ISO strings the API returns", () => {
    const iso = local(8, 9, 0).toISOString();
    expect(formatReminderTime(iso, WED_10AM)).toMatch(/^Tomorrow/);
  });
});
