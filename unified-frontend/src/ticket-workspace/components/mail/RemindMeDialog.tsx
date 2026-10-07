"use client";

import { useEffect, useMemo, useState } from "react";
import { Bell } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  buildPresets,
  formatReminderTime,
  parseCustomDateTime,
  toDateInputValue,
  toTimeInputValue,
  validateReminderDate,
  type ReminderDialogMode,
} from "@tw/lib/reminderPresets";

interface RemindMeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // create: new reminder · edit: change an ACTIVE reminder's time ·
  // snooze: push a due (or active) reminder to a later time.
  mode: ReminderDialogMode;
  // Existing reminder time, pre-filled into Custom for "edit".
  initialDate?: Date | null;
  // Resolves on success (dialog closes); a rejection's message is shown
  // inline and the dialog stays open so the choice isn't lost.
  onSubmit: (date: Date) => Promise<void>;
  // Injectable clock for tests.
  getNow?: () => Date;
}

const TITLES: Record<ReminderDialogMode, string> = {
  create: "Remind me",
  edit: "Edit reminder",
  snooze: "Snooze reminder",
};

const SUBMIT_LABELS: Record<ReminderDialogMode, string> = {
  create: "Set reminder",
  edit: "Save",
  snooze: "Snooze",
};

type Selection = { kind: "preset"; id: string } | { kind: "custom" };

export function RemindMeDialog({
  open,
  onOpenChange,
  mode,
  initialDate,
  onSubmit,
  getNow = () => new Date(),
}: RemindMeDialogProps) {
  // Presets are computed once per open so they don't shift under the
  // user's cursor while the dialog is showing.
  const [now, setNow] = useState<Date>(() => getNow());
  const [selection, setSelection] = useState<Selection | null>(null);
  const [customDate, setCustomDate] = useState("");
  const [customTime, setCustomTime] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const fresh = getNow();
    setNow(fresh);
    setError(null);
    setSubmitting(false);
    if (mode === "edit" && initialDate) {
      setSelection({ kind: "custom" });
      setCustomDate(toDateInputValue(initialDate));
      setCustomTime(toTimeInputValue(initialDate));
    } else {
      setSelection(null);
      setCustomDate("");
      setCustomTime("");
    }
    // Depend on the timestamp, not the Date object: callers build a new
    // Date each render and that must not reset what the user is typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, initialDate?.getTime()]);

  const presets = useMemo(() => buildPresets(now, mode), [now, mode]);

  const resolved = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "preset") {
      const p = presets.find((x) => x.id === selection.id);
      return p ? validateReminderDate(p.date, now) : null;
    }
    return parseCustomDateTime(customDate, customTime, now);
  }, [selection, presets, customDate, customTime, now]);

  const customError =
    selection?.kind === "custom" && (customDate || customTime) && resolved && !resolved.ok
      ? resolved.error
      : null;

  const canSubmit = !!resolved && resolved.ok && !submitting;

  async function handleSubmit() {
    // Re-validate against the clock at click time: a preset chosen long
    // ago (dialog left open) may have slipped into the past.
    const current = getNow();
    const check =
      selection?.kind === "preset"
        ? (() => {
            const p = presets.find((x) => x.id === selection.id);
            return p ? validateReminderDate(p.date, current) : null;
          })()
        : selection?.kind === "custom"
          ? parseCustomDateTime(customDate, customTime, current)
          : null;

    if (!check || !check.ok) {
      setError(check && !check.ok ? check.error : "Choose when to be reminded.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(check.date);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "Couldn't save the reminder.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" />
            {TITLES[mode]}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-2" role="group" aria-label="Reminder time">
          {presets.map((p) => {
            const selected = selection?.kind === "preset" && selection.id === p.id;
            return (
              <button
                key={p.id}
                type="button"
                data-testid={`remind-preset-${p.id}`}
                aria-pressed={selected}
                onClick={() => {
                  setSelection({ kind: "preset", id: p.id });
                  setError(null);
                }}
                className={cn(
                  "flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors",
                  selected
                    ? "border-primary bg-primary/10 text-foreground"
                    : "border-border hover:bg-muted"
                )}
              >
                <span className="font-medium">{p.label}</span>
                <span className="text-xs text-muted-foreground">
                  {formatReminderTime(p.date, now)}
                </span>
              </button>
            );
          })}

          <button
            type="button"
            data-testid="remind-preset-custom"
            aria-pressed={selection?.kind === "custom"}
            onClick={() => {
              setSelection({ kind: "custom" });
              setError(null);
            }}
            className={cn(
              "flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors",
              selection?.kind === "custom"
                ? "border-primary bg-primary/10 text-foreground"
                : "border-border hover:bg-muted"
            )}
          >
            <span className="font-medium">Custom</span>
            <span className="text-xs text-muted-foreground">Pick date &amp; time</span>
          </button>

          {selection?.kind === "custom" && (
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div className="space-y-1">
                <Label htmlFor="remind-date" className="text-xs">
                  Date
                </Label>
                <Input
                  id="remind-date"
                  type="date"
                  value={customDate}
                  min={toDateInputValue(now)}
                  onChange={(e) => {
                    setCustomDate(e.target.value);
                    setError(null);
                  }}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="remind-time" className="text-xs">
                  Time
                </Label>
                <Input
                  id="remind-time"
                  type="time"
                  value={customTime}
                  onChange={(e) => {
                    setCustomTime(e.target.value);
                    setError(null);
                  }}
                />
              </div>
            </div>
          )}
        </div>

        {(customError || error) && (
          <p role="alert" className="text-sm text-destructive">
            {error ?? customError}
          </p>
        )}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleSubmit()} disabled={!canSubmit}>
            {SUBMIT_LABELS[mode]}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
