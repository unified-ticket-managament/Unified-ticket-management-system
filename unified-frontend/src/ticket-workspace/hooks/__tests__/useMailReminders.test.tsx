import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MailReminder } from "@tw/api/mailReminders";
import { REMINDER_REFRESH_INTERVAL_MS, useMailReminders } from "@tw/hooks/useMailReminders";

const api = vi.hoisted(() => ({
  getReminders: vi.fn(),
  createReminder: vi.fn(),
  updateReminder: vi.fn(),
  cancelReminder: vi.fn(),
  snoozeReminder: vi.fn(),
  dismissReminder: vi.fn(),
}));
vi.mock("@tw/api/mailReminders", () => api);

function reminder(over: Partial<MailReminder> = {}): MailReminder {
  return {
    reminder_id: "r1",
    interaction_id: "i1",
    remind_at: "2026-10-08T09:00:00Z",
    status: "ACTIVE",
    snooze_count: 0,
    fired_at: null,
    completed_at: null,
    created_at: "2026-10-07T09:00:00Z",
    updated_at: "2026-10-07T09:00:00Z",
    ...over,
  };
}

// Server state the mocked list endpoint reads from.
let server: MailReminder[] = [];

beforeEach(() => {
  vi.clearAllMocks();
  server = [];
  api.getReminders.mockImplementation(async (p?: { status?: string }) =>
    server.filter((r) => !p?.status || r.status === p.status)
  );
  api.createReminder.mockImplementation(async (interactionId: string, at: Date) => {
    const r = reminder({
      reminder_id: `r${server.length + 1}`,
      interaction_id: interactionId,
      remind_at: at.toISOString(),
    });
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
    r.snooze_count += 1;
    return r;
  });
  api.dismissReminder.mockImplementation(async (id: string) => {
    const r = server.find((x) => x.reminder_id === id)!;
    r.status = "DISMISSED";
    return r;
  });
});
afterEach(() => vi.useRealTimers());

describe("useMailReminders", () => {
  it("loads the user's ACTIVE and FIRED reminders and keys them by thread", async () => {
    server = [
      reminder({ reminder_id: "a", interaction_id: "i1", status: "ACTIVE" }),
      reminder({ reminder_id: "f", interaction_id: "i2", status: "FIRED" }),
      reminder({ reminder_id: "d", interaction_id: "i3", status: "DISMISSED" }),
    ];

    const { result } = renderHook(() => useMailReminders());

    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(api.getReminders).toHaveBeenCalledWith({ status: "ACTIVE" });
    expect(api.getReminders).toHaveBeenCalledWith({ status: "FIRED" });
    expect(result.current.byInteractionId.get("i1")?.reminder_id).toBe("a");
    expect(result.current.byInteractionId.get("i2")?.reminder_id).toBe("f");
    expect(result.current.byInteractionId.has("i3")).toBe(false); // closed ones aren't shown
  });

  it("an ACTIVE reminder wins over a FIRED one on the same thread", async () => {
    server = [
      reminder({ reminder_id: "old", interaction_id: "i1", status: "FIRED" }),
      reminder({ reminder_id: "new", interaction_id: "i1", status: "ACTIVE" }),
    ];

    const { result } = renderHook(() => useMailReminders());

    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.byInteractionId.get("i1")?.reminder_id).toBe("new");
  });

  it("create → server call, then the map reflects it (R-041)", async () => {
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.byInteractionId.size).toBe(0);

    await act(async () => {
      await result.current.create("i9", new Date("2026-10-09T09:00:00Z"));
    });

    expect(api.createReminder).toHaveBeenCalledWith("i9", new Date("2026-10-09T09:00:00Z"));
    expect(result.current.byInteractionId.get("i9")?.status).toBe("ACTIVE");
  });

  it("update moves the time", async () => {
    server = [reminder()];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.size).toBe(1));

    await act(async () => {
      await result.current.update("r1", new Date("2026-11-01T10:00:00Z"));
    });

    expect(result.current.byInteractionId.get("i1")?.remind_at).toBe("2026-11-01T10:00:00.000Z");
  });

  it("cancel removes it from the map", async () => {
    server = [reminder()];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.size).toBe(1));

    await act(async () => {
      await result.current.cancel("r1");
    });

    expect(api.cancelReminder).toHaveBeenCalledWith("r1");
    expect(result.current.byInteractionId.size).toBe(0);
  });

  it("snooze turns a FIRED reminder back into an ACTIVE one", async () => {
    server = [reminder({ status: "FIRED" })];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.get("i1")?.status).toBe("FIRED"));

    await act(async () => {
      await result.current.snooze("r1", { minutes: 60 });
    });

    expect(api.snoozeReminder).toHaveBeenCalledWith("r1", { minutes: 60 });
    expect(result.current.byInteractionId.get("i1")?.status).toBe("ACTIVE");
  });

  it("dismiss clears a FIRED reminder", async () => {
    server = [reminder({ status: "FIRED" })];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.size).toBe(1));

    await act(async () => {
      await result.current.dismiss("r1");
    });

    expect(result.current.byInteractionId.size).toBe(0);
  });

  it("a failed mutation rejects to the caller and does not change state", async () => {
    server = [reminder()];
    api.cancelReminder.mockRejectedValueOnce(new Error("This reminder is already closed."));
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.size).toBe(1));

    await expect(
      act(async () => {
        await result.current.cancel("r1");
      })
    ).rejects.toThrow("already closed");

    expect(result.current.byInteractionId.size).toBe(1);
  });

  it("a failing background refresh never throws and keeps what it had", async () => {
    server = [reminder()];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.size).toBe(1));

    api.getReminders.mockRejectedValue(new Error("network down"));
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.byInteractionId.size).toBe(1);
  });

  it("an initial failure still finishes loading (mail is never blocked)", async () => {
    api.getReminders.mockRejectedValue(new Error("403"));
    const { result } = renderHook(() => useMailReminders());

    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.byInteractionId.size).toBe(0);
  });

  it("picks up a reminder that fired server-side when the tab regains focus (R-036)", async () => {
    server = [reminder({ status: "ACTIVE" })];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.byInteractionId.get("i1")?.status).toBe("ACTIVE"));

    server[0].status = "FIRED"; // the scheduler fired it while the tab was in the background
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(result.current.byInteractionId.get("i1")?.status).toBe("FIRED"));
  });

  it("refreshes when the tab becomes visible again", async () => {
    server = [reminder({ status: "ACTIVE" })];
    const { result } = renderHook(() => useMailReminders());
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    const before = api.getReminders.mock.calls.length;

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => expect(api.getReminders.mock.calls.length).toBeGreaterThan(before));
  });

  it("refreshes on an interval, and stops after unmount", async () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useMailReminders());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const afterMount = api.getReminders.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REMINDER_REFRESH_INTERVAL_MS + 100);
    });
    const afterTick = api.getReminders.mock.calls.length;
    expect(afterTick).toBeGreaterThan(afterMount);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(REMINDER_REFRESH_INTERVAL_MS * 3);
    });
    expect(api.getReminders.mock.calls.length).toBe(afterTick);
  });

  it("ignores a stale response that a newer refresh superseded", async () => {
    let releaseFirst: (v: MailReminder[]) => void = () => {};
    api.getReminders
      .mockImplementationOnce(() => new Promise<MailReminder[]>((r) => (releaseFirst = r))) // ACTIVE (slow, stale)
      .mockImplementationOnce(async () => []); // FIRED
    server = [reminder({ reminder_id: "new", status: "ACTIVE" })];

    const { result } = renderHook(() => useMailReminders());
    // A second refresh (reads the fresh server state) completes first…
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.byInteractionId.get("i1")?.reminder_id).toBe("new");

    // …then the stale one resolves with outdated data and must be dropped.
    await act(async () => {
      releaseFirst([reminder({ reminder_id: "stale" })]);
    });

    expect(result.current.byInteractionId.get("i1")?.reminder_id).toBe("new");
  });
});
