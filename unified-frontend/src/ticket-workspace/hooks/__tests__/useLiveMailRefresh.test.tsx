import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MAIL_EVENT_NAME, emitMailEvent, emitMailResync } from "@/lib/mail-events";
import { LIVE_MAIL_DEBOUNCE_MS, useLiveMailRefresh } from "@tw/hooks/useLiveMailRefresh";

// The coalescing/lifecycle rules of the live-mail refetch: bursts become
// one refetch, nothing is missed while one is running, a hidden tab does no
// work until it returns, there is exactly one listener, and a failure never
// escapes.

const created = (id = "i1") => emitMailEvent({ type: "mail.created", interaction_id: id });
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
}

beforeEach(() => {
  vi.useFakeTimers();
  setHidden(false);
});
afterEach(() => {
  vi.useRealTimers();
  setHidden(false);
});

describe("useLiveMailRefresh", () => {
  it("refetches after a mail event, without any manual Refresh", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    created();
    expect(refresh).not.toHaveBeenCalled(); // debounced, not instant
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("turns a burst of events into a single refetch", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    for (let i = 0; i < 12; i++) {
      created(`i${i}`);
      await advance(50); // each arrives inside the debounce window
    }
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("events that arrive during a running refetch cause exactly one more", async () => {
    let release!: () => void;
    const refresh = vi
      .fn()
      .mockImplementationOnce(() => new Promise<void>((r) => (release = r)))
      .mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    created();
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);
    expect(refresh).toHaveBeenCalledTimes(1); // running (not yet resolved)

    created("a");
    created("b");
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);
    expect(refresh).toHaveBeenCalledTimes(1); // never overlaps

    await act(async () => release());
    await advance(10);
    expect(refresh).toHaveBeenCalledTimes(2); // one catch-up run
  });

  it("a reconnect resync triggers a refetch too", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    emitMailResync();
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does no work while the tab is hidden, then refetches once when it returns", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));
    setHidden(true);

    created();
    created("b");
    await advance(LIVE_MAIL_DEBOUNCE_MS * 3);
    expect(refresh).not.toHaveBeenCalled();

    setHidden(false);
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await advance(10);

    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("returning to a tab with nothing pending does not refetch", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await advance(LIVE_MAIL_DEBOUNCE_MS * 2);

    expect(refresh).not.toHaveBeenCalled();
  });

  it("a failing refetch is swallowed and does not stop later updates", async () => {
    const refresh = vi.fn().mockRejectedValueOnce(new Error("boom")).mockResolvedValue(undefined);
    renderHook(() => useLiveMailRefresh(refresh));

    created();
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);
    created("again");
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);

    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("re-renders never add listeners; the latest callback is the one used", async () => {
    const add = vi.spyOn(window, "addEventListener");
    const first = vi.fn().mockResolvedValue(undefined);
    const second = vi.fn().mockResolvedValue(undefined);
    const { rerender } = renderHook(({ cb }) => useLiveMailRefresh(cb), {
      initialProps: { cb: first },
    });
    rerender({ cb: second });
    rerender({ cb: second });
    rerender({ cb: second });

    expect(add.mock.calls.filter(([name]) => name === MAIL_EVENT_NAME)).toHaveLength(1);

    created();
    await advance(LIVE_MAIL_DEBOUNCE_MS + 10);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    add.mockRestore();
  });

  it("cleans up on unmount: no listener, no pending timer, no late refetch", async () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useLiveMailRefresh(refresh));

    created(); // pending timer
    unmount();
    created("after unmount");
    await advance(LIVE_MAIL_DEBOUNCE_MS * 3);

    expect(refresh).not.toHaveBeenCalled();
    expect(remove.mock.calls.some(([name]) => name === MAIL_EVENT_NAME)).toBe(true);
    remove.mockRestore();
  });
});
