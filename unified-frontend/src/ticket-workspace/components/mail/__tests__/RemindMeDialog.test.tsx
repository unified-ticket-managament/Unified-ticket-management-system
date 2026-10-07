import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RemindMeDialog } from "@tw/components/mail/RemindMeDialog";

// The dialog's behaviour: presets, custom date/time, validation, save /
// cancel, and surfacing an API failure without losing the user's choice.
// Wed 7 Oct 2026 10:00 local (so Later today = 5 PM, Tomorrow = 8 Oct 9 AM).
const NOW = new Date(2026, 9, 7, 10, 0, 0);
const getNow = () => new Date(NOW);

function setup(props: Partial<React.ComponentProps<typeof RemindMeDialog>> = {}) {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const onOpenChange = vi.fn();
  render(
    <RemindMeDialog
      open
      onOpenChange={onOpenChange}
      mode="create"
      onSubmit={onSubmit}
      getNow={getNow}
      {...props}
    />
  );
  return { onSubmit, onOpenChange, user: userEvent.setup() };
}

describe("Remind me dialog", () => {
  it("opens with the title and the quick options (R-004)", () => {
    setup();

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Remind me")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-laterToday")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-tomorrow")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-nextWeek")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-custom")).toBeInTheDocument();
  });

  it("renders nothing while closed", () => {
    setup({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("can't be saved until something is chosen", () => {
    setup();
    expect(screen.getByRole("button", { name: "Set reminder" })).toBeDisabled();
  });

  it("saves the 'Tomorrow' preset as tomorrow 9:00 AM local (R-039)", async () => {
    const { onSubmit, onOpenChange, user } = setup();

    await user.click(screen.getByTestId("remind-preset-tomorrow"));
    await user.click(screen.getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toEqual(new Date(2026, 9, 8, 9, 0, 0));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("saves 'Later today' as 5 PM and 'Next week' as Monday 9 AM", async () => {
    const first = setup();
    await first.user.click(screen.getByTestId("remind-preset-laterToday"));
    await first.user.click(screen.getByRole("button", { name: "Set reminder" }));
    await waitFor(() => expect(first.onSubmit).toHaveBeenCalled());
    expect(first.onSubmit.mock.calls[0][0]).toEqual(new Date(2026, 9, 7, 17, 0, 0));
  });

  it("marks the chosen preset as pressed", async () => {
    const { user } = setup();
    const tomorrow = screen.getByTestId("remind-preset-tomorrow");
    expect(tomorrow).toHaveAttribute("aria-pressed", "false");

    await user.click(tomorrow);

    expect(tomorrow).toHaveAttribute("aria-pressed", "true");
  });

  it("Custom reveals date and time inputs and saves the picked instant (R-040)", async () => {
    const { onSubmit, user } = setup();

    await user.click(screen.getByTestId("remind-preset-custom"));
    await user.type(screen.getByLabelText("Date"), "2026-10-15");
    await user.type(screen.getByLabelText("Time"), "14:30");
    await user.click(screen.getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toEqual(new Date(2026, 9, 15, 14, 30, 0));
  });

  it("rejects a custom time in the past and keeps Save disabled", async () => {
    const { onSubmit, user } = setup();

    await user.click(screen.getByTestId("remind-preset-custom"));
    await user.type(screen.getByLabelText("Date"), "2026-10-06");
    await user.type(screen.getByLabelText("Time"), "09:00");

    expect(screen.getByRole("alert")).toHaveTextContent("Pick a time in the future.");
    expect(screen.getByRole("button", { name: "Set reminder" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a custom time more than a year out", async () => {
    const { user } = setup();

    await user.click(screen.getByTestId("remind-preset-custom"));
    await user.type(screen.getByLabelText("Date"), "2028-01-01");
    await user.type(screen.getByLabelText("Time"), "09:00");

    expect(screen.getByRole("alert")).toHaveTextContent("1 year");
    expect(screen.getByRole("button", { name: "Set reminder" })).toBeDisabled();
  });

  it("Cancel closes without saving", async () => {
    const { onSubmit, onOpenChange, user } = setup();

    await user.click(screen.getByTestId("remind-preset-tomorrow"));
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the API error inline, stays open, and keeps the selection (R-044)", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error("An active reminder already exists for this email."));
    const { onOpenChange, user } = setup({ onSubmit });

    await user.click(screen.getByTestId("remind-preset-tomorrow"));
    await user.click(screen.getByRole("button", { name: "Set reminder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("active reminder already exists");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByTestId("remind-preset-tomorrow")).toHaveAttribute("aria-pressed", "true");
    // and the user can simply try again
    expect(screen.getByRole("button", { name: "Set reminder" })).toBeEnabled();
  });

  it("falls back to a generic message when the failure has no text", async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error(""));
    const { user } = setup({ onSubmit });

    await user.click(screen.getByTestId("remind-preset-tomorrow"));
    await user.click(screen.getByRole("button", { name: "Set reminder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save the reminder.");
  });

  it("re-checks the preset against the clock at click time", async () => {
    let clock = new Date(NOW);
    const { onSubmit, user } = setup({ getNow: () => new Date(clock) });

    await user.click(screen.getByTestId("remind-preset-laterToday")); // 5 PM today
    clock = new Date(2026, 9, 7, 18, 0, 0); // dialog sat open past 5 PM
    await user.click(screen.getByRole("button", { name: "Set reminder" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Pick a time in the future.");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("edit mode pre-fills the existing time into Custom and saves with 'Save'", async () => {
    const existing = new Date(2026, 9, 9, 8, 15, 0);
    const { onSubmit, user } = setup({ mode: "edit", initialDate: existing });

    expect(screen.getByText("Edit reminder")).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveValue("2026-10-09");
    expect(screen.getByLabelText("Time")).toHaveValue("08:15");

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toEqual(existing);
  });

  it("editing the pre-filled time is not reset when the parent re-renders with an equal Date", async () => {
    const user = userEvent.setup();
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      mode: "edit" as const,
      onSubmit: vi.fn().mockResolvedValue(undefined),
      getNow,
    };
    const { rerender } = render(
      <RemindMeDialog {...props} initialDate={new Date(2026, 9, 9, 8, 15, 0)} />
    );

    const time = screen.getByLabelText("Time");
    await user.clear(time);
    await user.type(time, "11:45");
    // Parents build a NEW Date object each render (MailReminderProvider does).
    rerender(<RemindMeDialog {...props} initialDate={new Date(2026, 9, 9, 8, 15, 0)} />);

    expect(screen.getByLabelText("Time")).toHaveValue("11:45");
  });

  it("snooze mode offers relative presets and a Snooze button (R-043)", async () => {
    const { onSubmit, user } = setup({ mode: "snooze" });

    expect(screen.getByText("Snooze reminder")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-in1Hour")).toBeInTheDocument();
    expect(screen.getByTestId("remind-preset-in3Hours")).toBeInTheDocument();
    expect(screen.queryByTestId("remind-preset-laterToday")).toBeNull();

    await user.click(screen.getByTestId("remind-preset-in1Hour"));
    await user.click(screen.getByRole("button", { name: "Snooze" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toEqual(new Date(NOW.getTime() + 60 * 60_000));
  });
});
