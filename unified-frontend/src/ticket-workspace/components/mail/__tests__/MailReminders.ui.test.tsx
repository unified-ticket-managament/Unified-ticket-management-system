import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MailReminder } from "@tw/api/mailReminders";
import {
  ReminderRowIcon,
  ReminderStatusBar,
  RemindMeToolbarButton,
} from "@tw/components/mail/MailReminderIndicators";
import { MailReminderProvider } from "@tw/components/mail/MailReminderContext";
import { MessageActionsMenu } from "@tw/components/mail/MessageActionsMenu";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { InboxItem } from "@tw/types";

// Reminder UI wired to the REAL provider + hook, with only the network
// layer, toasts and auth mocked: indicators, the due banner (snooze /
// dismiss), edit / remove, creating from the menus, and the menus' own
// gating (no "Remind me" for synthetic rows).

const api = vi.hoisted(() => ({
  getReminders: vi.fn(),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  cancelReminder: vi.fn(),
  snoozeReminder: vi.fn(),
  dismissReminder: vi.fn(),
}));
vi.mock("@tw/api/mailReminders", () => api);

const pushToast = vi.hoisted(() => vi.fn());
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: { user_id: "u1", permissions: ["communication:reply_external"] },
  }),
}));
vi.mock("@tw/components/mail/MailBulkContext", () => ({
  useMailBulk: () => ({
    isTrash: false,
    perms: {},
    selectedIds: new Set(),
    markMessage: vi.fn(),
    runBulk: vi.fn(),
    clear: vi.fn(),
  }),
}));

const DAY = 24 * 60 * 60_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

function reminder(over: Partial<MailReminder> = {}): MailReminder {
  return {
    reminder_id: "r1",
    interaction_id: "i1",
    remind_at: iso(DAY),
    status: "ACTIVE",
    snooze_count: 0,
    fired_at: null,
    completed_at: null,
    created_at: iso(-DAY),
    updated_at: iso(-DAY),
    ...over,
  };
}

let server: MailReminder[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  server = [];
  api.getReminders.mockImplementation(async (p?: { status?: string }) =>
    server.filter((r) => !p?.status || r.status === p.status)
  );
  api.createReminder.mockImplementation(async (interactionId: string, at: Date) => {
    const r = reminder({ reminder_id: "new1", interaction_id: interactionId, remind_at: at.toISOString() });
    server.push(r);
    return r;
  });
  api.updateReminder.mockImplementation(async (id: string, at: Date) => {
    const r = server.find((x) => x.reminder_id === id)!;
    r.remind_at = at.toISOString();
    return r;
  });
  api.cancelReminder.mockImplementation(async (id: string) => {
    server.find((x) => x.reminder_id === id)!.status = "CANCELED";
  });
  api.snoozeReminder.mockImplementation(async (id: string) => {
    const r = server.find((x) => x.reminder_id === id)!;
    r.status = "ACTIVE";
    return r;
  });
  api.dismissReminder.mockImplementation(async (id: string) => {
    server.find((x) => x.reminder_id === id)!.status = "DISMISSED";
    return server[0];
  });
});

function withProvider(ui: React.ReactNode) {
  return (
    <MemoryRouter>
      <TooltipProvider>
        <MailReminderProvider>{ui}</MailReminderProvider>
      </TooltipProvider>
    </MemoryRouter>
  );
}

const item = (over: Record<string, unknown> = {}) =>
  ({
    interaction_id: "i1",
    ticket_id: null,
    status: "PENDING",
    is_read: true,
    folder_id: null,
    ...over,
  }) as unknown as InboxItem;

function menu(over: Record<string, unknown> = {}) {
  return (
    <MessageActionsMenu
      item={item(over)}
      isUnread={false}
      folders={[]}
      onMessageAction={vi.fn()}
      onMarkRead={vi.fn()}
      onMarkUnread={vi.fn()}
      onAssignFolder={vi.fn().mockResolvedValue(true)}
    />
  );
}

describe("reminder indicator and details (R-041)", () => {
  it("shows the active reminder with its time, in the reading pane", async () => {
    server = [reminder({ remind_at: new Date(2030, 0, 15, 9, 0).toISOString() })];

    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    const chip = await screen.findByTestId("reminder-chip");
    expect(chip).toHaveTextContent(/Reminder:\s*Jan 15, 2030, 9:00\s?AM/);
    expect(within(chip).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(chip).getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("renders nothing for an email without a reminder", async () => {
    server = [reminder({ interaction_id: "other" })];

    const { container } = render(withProvider(<ReminderStatusBar interactionId="i1" />));
    await waitFor(() => expect(api.getReminders).toHaveBeenCalled());

    expect(container.querySelector("[data-testid]")).toBeNull();
  });

  it("renders nothing at all outside a provider (screens that don't opt in are unchanged)", () => {
    const { container } = render(
      <>
        <ReminderStatusBar interactionId="i1" />
        <RemindMeToolbarButton interactionId="i1" />
        <ReminderRowIcon interactionId="i1" />
      </>
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("the list row gets a bell for an active reminder and a highlighted one for a due reminder", async () => {
    server = [
      reminder({ reminder_id: "a", interaction_id: "i1", status: "ACTIVE" }),
      reminder({ reminder_id: "f", interaction_id: "i2", status: "FIRED" }),
    ];

    render(
      withProvider(
        <>
          <ReminderRowIcon interactionId="i1" />
          <ReminderRowIcon interactionId="i2" />
          <ReminderRowIcon interactionId="i3" />
        </>
      )
    );

    expect(await screen.findByLabelText(/^Reminder: /)).toBeInTheDocument();
    expect(await screen.findByLabelText("Reminder due")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^Reminder/)).toHaveLength(2); // none for i3
  });
});

describe("edit and remove (R-042)", () => {
  it("Edit opens the dialog pre-filled and saving updates the reminder", async () => {
    const existing = new Date();
    existing.setDate(existing.getDate() + 20);
    existing.setHours(9, 0, 0, 0);
    server = [reminder({ remind_at: existing.toISOString() })];
    const pad = (n: number) => String(n).padStart(2, "0");
    const dateValue = `${existing.getFullYear()}-${pad(existing.getMonth() + 1)}-${pad(existing.getDate())}`;
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Edit" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Edit reminder")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Date")).toHaveValue(dateValue);
    expect(within(dialog).getByLabelText("Time")).toHaveValue("09:00");

    const time = within(dialog).getByLabelText("Time");
    await user.clear(time);
    await user.type(time, "16:30");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.updateReminder).toHaveBeenCalledTimes(1));
    const expected = new Date(existing);
    expected.setHours(16, 30, 0, 0);
    expect(api.updateReminder).toHaveBeenCalledWith("r1", expected);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("Reminder moved to"), "success");
  });

  it("Remove cancels the reminder and the indicator disappears", async () => {
    server = [reminder()];
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Remove" }));

    await waitFor(() => expect(api.cancelReminder).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(screen.queryByTestId("reminder-chip")).toBeNull());
    expect(pushToast).toHaveBeenCalledWith("Reminder removed", "success");
  });

  it("a failed Remove shows an error toast and keeps the indicator", async () => {
    server = [reminder()];
    api.cancelReminder.mockRejectedValueOnce(new Error("This reminder is already closed."));
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(pushToast).toHaveBeenCalledWith("This reminder is already closed.", "error")
    );
    expect(screen.getByTestId("reminder-chip")).toBeInTheDocument();
  });
});

describe("due reminder banner (R-043)", () => {
  it("shows 'Reminder due' with Snooze and Dismiss for a fired reminder", async () => {
    server = [reminder({ status: "FIRED", fired_at: iso(-60_000) })];

    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    const banner = await screen.findByTestId("reminder-due-banner");
    expect(banner).toHaveTextContent("Reminder due");
    expect(within(banner).getByRole("button", { name: "Snooze" })).toBeInTheDocument();
    expect(within(banner).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.queryByTestId("reminder-chip")).toBeNull();
  });

  it("Snooze → pick 1 hour → snoozes to that absolute time and the banner is replaced by the chip", async () => {
    server = [reminder({ status: "FIRED" })];
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Snooze" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Snooze reminder")).toBeInTheDocument();
    const before = Date.now();
    await user.click(within(dialog).getByTestId("remind-preset-in1Hour"));
    await user.click(within(dialog).getByRole("button", { name: "Snooze" }));

    await waitFor(() => expect(api.snoozeReminder).toHaveBeenCalledTimes(1));
    const [id, target] = api.snoozeReminder.mock.calls[0];
    expect(id).toBe("r1");
    const when = new Date(target.remind_at).getTime();
    expect(when).toBeGreaterThanOrEqual(before + 60 * 60_000 - 5_000);
    expect(when).toBeLessThanOrEqual(Date.now() + 60 * 60_000 + 5_000);
    expect(await screen.findByTestId("reminder-chip")).toBeInTheDocument();
    expect(screen.queryByTestId("reminder-due-banner")).toBeNull();
    expect(pushToast).toHaveBeenCalledWith(expect.stringContaining("Snoozed until"), "success");
  });

  it("Dismiss acknowledges it and clears the banner", async () => {
    server = [reminder({ status: "FIRED" })];
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(api.dismissReminder).toHaveBeenCalledWith("r1"));
    await waitFor(() => expect(screen.queryByTestId("reminder-due-banner")).toBeNull());
    expect(pushToast).toHaveBeenCalledWith("Reminder dismissed", "success");
  });

  it("a snooze rejected by the server shows the error in the dialog", async () => {
    server = [reminder({ status: "FIRED" })];
    api.snoozeReminder.mockRejectedValueOnce(new Error("This reminder can no longer be snoozed."));
    const user = userEvent.setup();
    render(withProvider(<ReminderStatusBar interactionId="i1" />));

    await user.click(await screen.findByRole("button", { name: "Snooze" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-in3Hours"));
    await user.click(within(dialog).getByRole("button", { name: "Snooze" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("can no longer be snoozed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("creating a reminder from the toolbar", () => {
  it("Remind me → Tomorrow → Set reminder creates it for that thread and offers Undo", async () => {
    const user = userEvent.setup();
    render(withProvider(<RemindMeToolbarButton interactionId="i1" />));

    await user.click(screen.getByRole("button", { name: "Remind me" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-tomorrow"));
    await user.click(within(dialog).getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(api.createReminder).toHaveBeenCalledTimes(1));
    const [interactionId, when] = api.createReminder.mock.calls[0];
    expect(interactionId).toBe("i1");
    const tomorrow9 = new Date();
    tomorrow9.setDate(tomorrow9.getDate() + 1);
    tomorrow9.setHours(9, 0, 0, 0);
    expect(when).toEqual(tomorrow9);

    // the button now manages the reminder instead
    expect(await screen.findByRole("button", { name: "Edit reminder" })).toBeInTheDocument();

    // toast carries an Undo that cancels it
    const call = pushToast.mock.calls.find(([m]) => String(m).startsWith("Reminder set for"));
    expect(call).toBeTruthy();
    call![2].action.onClick();
    await waitFor(() => expect(api.cancelReminder).toHaveBeenCalledWith("new1"));
  });

  it("Cancel in the dialog creates nothing", async () => {
    const user = userEvent.setup();
    render(withProvider(<RemindMeToolbarButton interactionId="i1" />));

    await user.click(screen.getByRole("button", { name: "Remind me" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.createReminder).not.toHaveBeenCalled();
  });

  it("a server rejection (e.g. duplicate) is shown inline and nothing is created", async () => {
    api.createReminder.mockRejectedValueOnce(
      new Error("An active reminder already exists for this email.")
    );
    const user = userEvent.setup();
    render(withProvider(<RemindMeToolbarButton interactionId="i1" />));

    await user.click(screen.getByRole("button", { name: "Remind me" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-tomorrow"));
    await user.click(within(dialog).getByRole("button", { name: "Set reminder" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already exists");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("with a fired reminder the button still offers a fresh 'Remind me'", async () => {
    server = [reminder({ status: "FIRED" })];
    render(withProvider(<RemindMeToolbarButton interactionId="i1" />));

    expect(await screen.findByRole("button", { name: "Remind me" })).toBeInTheDocument();
  });
});

describe("row ⋮ menu (R-038)", () => {
  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole("button", { name: "More actions" }));
    return screen.findByRole("menu");
  }

  it("lists Remind me", async () => {
    const user = userEvent.setup();
    render(withProvider(menu()));

    const m = await openMenu(user);

    expect(within(m).getByRole("menuitem", { name: /Remind me/ })).toBeInTheDocument();
    // existing actions are still there, in their original place
    expect(within(m).getByRole("menuitem", { name: /Mark as unread/ })).toBeInTheDocument();
    expect(within(m).getByRole("menuitem", { name: /Reply$/ })).toBeInTheDocument();
  });

  it("choosing it opens the dialog and creates the reminder for that row", async () => {
    const user = userEvent.setup();
    render(withProvider(menu()));

    const m = await openMenu(user);
    await user.click(within(m).getByRole("menuitem", { name: /Remind me/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-nextWeek"));
    await user.click(within(dialog).getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(api.createReminder).toHaveBeenCalledTimes(1));
    expect(api.createReminder.mock.calls[0][0]).toBe("i1");
  });

  it("uses the open-id for Sent/Draft rows (their own id isn't the thread)", async () => {
    const user = userEvent.setup();
    render(withProvider(menu({ interaction_id: "sent-row", open_interaction_id: "thread-root" })));

    const m = await openMenu(user);
    await user.click(within(m).getByRole("menuitem", { name: /Remind me/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByTestId("remind-preset-tomorrow"));
    await user.click(within(dialog).getByRole("button", { name: "Set reminder" }));

    await waitFor(() => expect(api.createReminder).toHaveBeenCalled());
    expect(api.createReminder.mock.calls[0][0]).toBe("thread-root");
  });

  it("an existing reminder turns the item into 'Edit reminder'", async () => {
    server = [reminder()];
    const user = userEvent.setup();
    render(
      withProvider(
        <>
          <ReminderRowIcon interactionId="i1" />
          {menu()}
        </>
      )
    );
    // the bell proves the reminder map has loaded before the menu opens
    await screen.findByLabelText(/^Reminder: /);

    const m = await openMenu(user);

    expect(within(m).getByRole("menuitem", { name: /Edit reminder/ })).toBeInTheDocument();
    expect(within(m).queryByRole("menuitem", { name: /^Remind me/ })).toBeNull();
  });

  it.each([
    ["an OTP-forward synthetic row", { interaction_id: "otp-forward:123" }],
    ["a compose draft", { is_compose_draft: true }],
  ])("is not offered for %s", (_label, over) => {
    render(withProvider(menu(over)));
    expect(screen.queryByRole("button", { name: "More actions" })).toBeNull();
  });

  it("is simply absent (menu otherwise unchanged) when there is no reminder provider", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <TooltipProvider>{menu()}</TooltipProvider>
      </MemoryRouter>
    );

    const m = await openMenu(user);

    expect(within(m).queryByRole("menuitem", { name: /Remind me/ })).toBeNull();
    expect(within(m).getByRole("menuitem", { name: /Mark as unread/ })).toBeInTheDocument();
  });
});
