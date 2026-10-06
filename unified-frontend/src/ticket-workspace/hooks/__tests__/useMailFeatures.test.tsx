import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getMailFeatures } from "@tw/api/inbox";
import { resetMailFeaturesCacheForTests, useMailFeatures } from "@tw/hooks/useMailFeatures";

vi.mock("@tw/api/inbox", () => ({ getMailFeatures: vi.fn() }));

beforeEach(() => {
  resetMailFeaturesCacheForTests();
  vi.mocked(getMailFeatures).mockReset();
});

describe("useMailFeatures", () => {
  it("is OFF while loading, then reflects the backend setting", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: true });
    const { result } = renderHook(() => useMailFeatures());

    expect(result.current.read_receipts_enabled).toBe(false); // loading
    await waitFor(() => expect(result.current.read_receipts_enabled).toBe(true));
  });

  it("stays OFF when the backend says off", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: false });
    const { result } = renderHook(() => useMailFeatures());

    await waitFor(() => expect(getMailFeatures).toHaveBeenCalled());
    expect(result.current.read_receipts_enabled).toBe(false);
  });

  it("stays OFF when the lookup fails", async () => {
    vi.mocked(getMailFeatures).mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useMailFeatures());

    await waitFor(() => expect(getMailFeatures).toHaveBeenCalled());
    expect(result.current.read_receipts_enabled).toBe(false);
  });

  it("treats anything other than an explicit true as OFF", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({
      read_receipts_enabled: "yes" as unknown as boolean,
    });
    const { result } = renderHook(() => useMailFeatures());

    await waitFor(() => expect(getMailFeatures).toHaveBeenCalled());
    expect(result.current.read_receipts_enabled).toBe(false);
  });

  it("looks the setting up once and shares it across every consumer", async () => {
    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: true });
    const first = renderHook(() => useMailFeatures());
    const second = renderHook(() => useMailFeatures());
    await waitFor(() => expect(first.result.current.read_receipts_enabled).toBe(true));
    await waitFor(() => expect(second.result.current.read_receipts_enabled).toBe(true));

    // A later consumer starts with the cached answer immediately.
    const late = renderHook(() => useMailFeatures());
    expect(late.result.current.read_receipts_enabled).toBe(true);
    expect(getMailFeatures).toHaveBeenCalledTimes(1);
  });

  it("does not cache a failure: the next consumer retries", async () => {
    vi.mocked(getMailFeatures).mockRejectedValueOnce(new Error("network"));
    const first = renderHook(() => useMailFeatures());
    await waitFor(() => expect(getMailFeatures).toHaveBeenCalledTimes(1));
    expect(first.result.current.read_receipts_enabled).toBe(false);

    vi.mocked(getMailFeatures).mockResolvedValue({ read_receipts_enabled: true });
    const second = renderHook(() => useMailFeatures());
    await waitFor(() => expect(second.result.current.read_receipts_enabled).toBe(true));
    expect(getMailFeatures).toHaveBeenCalledTimes(2);
  });
});
