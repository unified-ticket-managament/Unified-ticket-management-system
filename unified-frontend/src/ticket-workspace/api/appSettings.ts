import { apiClient } from "./client";

// GET/PUT /app-settings/read-receipts — the global Read Receipts switch
// (Settings > Email & Communication). Readable by any agent; only holders
// of `ticket:system_config` (Super Admin by default) can change it, which
// the server re-checks on every update.
export interface ReadReceiptSetting {
  // Whether agents may request read receipts (default OFF).
  read_receipts_enabled: boolean;
  // Whether THIS user may change the setting.
  can_manage: boolean;
}

export async function getReadReceiptSetting(): Promise<ReadReceiptSetting> {
  const { data } = await apiClient.get<ReadReceiptSetting>("/app-settings/read-receipts");
  return data;
}

export async function updateReadReceiptSetting(enabled: boolean): Promise<ReadReceiptSetting> {
  const { data } = await apiClient.put<ReadReceiptSetting>("/app-settings/read-receipts", {
    enabled,
  });
  return data;
}
