import { beforeEach, describe, expect, it, vi } from "vitest";

import { getReadReceiptSetting, updateReadReceiptSetting } from "@tw/api/appSettings";

const client = vi.hoisted(() => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));
vi.mock("@tw/api/client", () => client);

beforeEach(() => vi.clearAllMocks());

describe("app settings API", () => {
  it("reads the current Read Receipts setting", async () => {
    client.apiClient.get.mockResolvedValue({ data: { read_receipts_enabled: true, can_manage: false } });

    await expect(getReadReceiptSetting()).resolves.toEqual({
      read_receipts_enabled: true,
      can_manage: false,
    });
    expect(client.apiClient.get).toHaveBeenCalledWith("/app-settings/read-receipts");
  });

  it.each([true, false])("updates it with PUT { enabled: %s }", async (enabled) => {
    client.apiClient.put.mockResolvedValue({ data: { read_receipts_enabled: enabled, can_manage: true } });

    const saved = await updateReadReceiptSetting(enabled);

    expect(client.apiClient.put).toHaveBeenCalledWith("/app-settings/read-receipts", { enabled });
    expect(saved.read_receipts_enabled).toBe(enabled);
  });
});
