import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopNavbar } from "@/components/layout/top-navbar";
import { subscribeMailEvents, type MailEventDetail } from "@/lib/mail-events";

// The navbar owns the app's ONE notification EventSource. These tests cover
// its role in live mail: it re-broadcasts the backend's `mail` events to the
// Mail workspace over that same connection, asks the Mail view to resync
// after a RECONNECT, backs off between attempts, and never opens a second
// connection or leaks one on unmount.

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => ({ toast: vi.fn() }) }));
vi.mock("@/services", () => ({ authService: { logout: vi.fn() } }));
vi.mock("@/store/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) =>
    selector({ user: { name: "Admin", email: "a@x.com", role: "Super Admin" }, logout: vi.fn() }),
}));
vi.mock("@/lib/notifications-api", () => ({
  dismissAllNotifications: vi.fn(),
  getNotifications: vi.fn().mockResolvedValue({ notifications: [], unread_count: 0 }),
  getNotificationStreamUrl: (token: string) => `http://api.test/notifications/stream?token=${token}`,
  markAllNotificationsRead: vi.fn(),
  markNotificationRead: vi.fn(),
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, Array<(e: MessageEvent) => void>>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, handler: (e: MessageEvent) => void) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), handler]);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  fail() {
    this.onerror?.();
  }
  emit(name: string, data: string) {
    (this.listeners.get(name) ?? []).forEach((h) => h({ data } as MessageEvent));
  }
}

const received: MailEventDetail[] = [];
let unsubscribe: () => void;

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  received.length = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
  localStorage.setItem("access_token", "tok123");
  unsubscribe = subscribeMailEvents((d) => received.push(d));
});
afterEach(() => {
  unsubscribe();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const latest = () => FakeEventSource.instances.at(-1)!;
const mailEvent = (extra: object = {}) =>
  JSON.stringify({ type: "mail.created", interaction_id: "i1", thread_id: "i1", ticket_id: null, ...extra });

describe("the navbar's notification stream and live mail", () => {
  it("opens exactly one authenticated stream, and re-renders do not open another", async () => {
    const { rerender } = render(<TopNavbar />);
    await act(async () => {});
    rerender(<TopNavbar />);
    rerender(<TopNavbar />);

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(latest().url).toBe("http://api.test/notifications/stream?token=tok123");
  });

  it("re-broadcasts a `mail` event to the Mail workspace", async () => {
    render(<TopNavbar />);
    await act(async () => {});

    act(() => latest().emit("mail", mailEvent()));

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ type: "mail.created", interaction_id: "i1" });
  });

  it("ignores malformed or unknown mail payloads", async () => {
    render(<TopNavbar />);
    await act(async () => {});

    act(() => {
      latest().emit("mail", "{nope");
      latest().emit("mail", JSON.stringify({ type: "something.else" }));
    });

    expect(received).toHaveLength(0);
  });

  it("does not ask for a resync on the FIRST connection", async () => {
    render(<TopNavbar />);
    await act(async () => {});

    act(() => latest().open());

    expect(received).toHaveLength(0);
  });

  it("after a drop it reconnects with backoff, then asks the Mail view to resync", async () => {
    render(<TopNavbar />);
    await act(async () => {});
    act(() => latest().open());
    const first = latest();

    act(() => first.fail());
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1); // not instantly: it backs off

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(FakeEventSource.instances).toHaveLength(2);

    act(() => latest().open()); // the reconnect succeeded
    expect(received).toEqual([{ type: "mail.resync" }]);
  });

  it("repeated failures back off exponentially instead of looping", async () => {
    render(<TopNavbar />);
    await act(async () => {});

    act(() => latest().fail()); // attempt 1 -> 1s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    act(() => latest().fail()); // attempt 2 -> 2s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(FakeEventSource.instances).toHaveLength(2); // still waiting (needs 2s)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it("closes the stream and cancels a pending reconnect on unmount", async () => {
    const { unmount } = render(<TopNavbar />);
    await act(async () => {});
    const first = latest();
    act(() => first.fail()); // schedules a reconnect

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(FakeEventSource.instances).toHaveLength(1); // no reconnect after unmount

    const second = render(<TopNavbar />);
    await act(async () => {});
    const open = latest();
    second.unmount();
    expect(open.closed).toBe(true);
  });
});
