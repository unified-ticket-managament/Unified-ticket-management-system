import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopNavbar } from "@/components/layout/top-navbar";

// A due-reminder notification (MAIL_REMINDER_DUE) through the EXISTING bell:
// it arrives over the existing notification stream, shows in the dropdown,
// and clicking it marks it read and opens the original email via the
// existing /inbox?interaction_id= deep link (R-005 R-006 R-035 R-036 R-045).
// Nothing reminder-specific is needed in the navbar — these tests pin that.

const push = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
const notificationsApi = vi.hoisted(() => ({
  dismissAllNotifications: vi.fn(),
  getNotifications: vi.fn(),
  getNotificationStreamUrl: (token: string) => `http://api.test/notifications/stream?token=${token}`,
  markAllNotificationsRead: vi.fn(),
  markNotificationRead: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast }) }));
vi.mock("@/services", () => ({ authService: { logout: vi.fn() } }));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { name: "Admin", email: "a@x.com", role: "Super Admin" }, logout: vi.fn() }),
}));
vi.mock("@/lib/notifications-api", () => notificationsApi);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, Array<(e: MessageEvent) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, handler: (e: MessageEvent) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
  }
  close() {}
  emit(name: string, data: string) {
    (this.listeners.get(name) ?? []).forEach((h) => h({ data } as MessageEvent));
  }
}

const INTERACTION_ID = "3f2b8c1e-0000-4000-8000-00000000abcd";

function reminderNotification(over: Record<string, unknown> = {}) {
  return {
    notification_id: "n-rem-1",
    notification_type: "MAIL_REMINDER_DUE",
    title: "Mail Reminder",
    message: "Reminder: Quarterly invoice question",
    link: `/inbox?interaction_id=${INTERACTION_ID}`,
    related_entity_type: "interaction",
    related_entity_id: INTERACTION_ID,
    is_read: false,
    created_at: new Date().toISOString(),
    ...over,
  };
}

const stream = () => FakeEventSource.instances.at(-1)!;
const deliver = (n: object) =>
  act(() => stream().emit("notification", JSON.stringify({ notification: n, unread_count: 1 })));

async function openBell(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /notifications/i }));
  return screen.findByRole("menu");
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.clearAllMocks();
  notificationsApi.getNotifications.mockResolvedValue({ items: [], total: 0, unread_count: 0 });
  notificationsApi.markNotificationRead.mockResolvedValue(undefined);
  vi.stubGlobal("EventSource", FakeEventSource);
  localStorage.setItem("access_token", "tok123");
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("a due-reminder notification in the bell", () => {
  it("appears when it arrives over the existing stream, with the title and subject", async () => {
    const user = userEvent.setup();
    render(<TopNavbar />);
    await act(async () => {});

    deliver(reminderNotification());

    const menu = await openBell(user);
    expect(within(menu).getByText("Mail Reminder")).toBeInTheDocument();
    expect(within(menu).getByText(/Reminder: Quarterly invoice question/)).toBeInTheDocument();
  });

  it("raises the unread count", async () => {
    render(<TopNavbar />);
    await act(async () => {});

    deliver(reminderNotification());

    const bell = screen.getByRole("button", { name: /notifications/i });
    await waitFor(() => expect(within(bell).getByText("1")).toBeInTheDocument());
  });

  it("is shown once even if the stream delivers it twice", async () => {
    const user = userEvent.setup();
    render(<TopNavbar />);
    await act(async () => {});

    deliver(reminderNotification());
    deliver(reminderNotification());

    const menu = await openBell(user);
    expect(within(menu).getAllByText("Mail Reminder")).toHaveLength(1);
  });

  it("is waiting after the user was offline: loaded from the notification list on mount", async () => {
    notificationsApi.getNotifications.mockResolvedValue({
      items: [reminderNotification()],
      total: 1,
      unread_count: 1,
    });
    const user = userEvent.setup();
    render(<TopNavbar />);
    await act(async () => {});

    const menu = await openBell(user);

    expect(within(menu).getByText("Mail Reminder")).toBeInTheDocument();
  });

  it("clicking it marks it read and opens THE original email (deep link under /dashboard)", async () => {
    const user = userEvent.setup();
    render(<TopNavbar />);
    await act(async () => {});
    deliver(reminderNotification());

    const menu = await openBell(user);
    await user.click(within(menu).getByText("Mail Reminder"));

    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/dashboard/inbox?interaction_id=${INTERACTION_ID}`)
    );
    expect(notificationsApi.markNotificationRead).toHaveBeenCalledWith("n-rem-1");
  });

  it("does not disturb other notifications that arrive alongside it", async () => {
    const user = userEvent.setup();
    render(<TopNavbar />);
    await act(async () => {});

    deliver({
      notification_id: "n-assign",
      notification_type: "TICKET_ASSIGNED",
      title: "Ticket assigned",
      message: "Ticket T-1 was assigned to you",
      link: "/tickets/abc",
      related_entity_type: "ticket",
      related_entity_id: "abc",
      is_read: false,
      created_at: new Date().toISOString(),
    });
    deliver(reminderNotification());

    const menu = await openBell(user);
    expect(within(menu).getByText("Ticket assigned")).toBeInTheDocument();
    expect(within(menu).getByText("Mail Reminder")).toBeInTheDocument();

    await user.click(within(menu).getByText("Ticket assigned"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/tickets/abc"));
  });
});
