import { apiClient } from "./client";
import type { NotificationItem, NotificationListResponse } from "@tw/types";

// The notifications router lives unprefixed on the unified backend
// (same as every other ticketing route this workspace's `apiClient`
// already targets) — no baseURL override needed here, unlike the
// shell app's own src/lib/notifications-api.ts (whose default `api`
// instance is baseURL'd to .../api/v1 instead).

export async function getNotifications(options?: {
  unreadOnly?: boolean;
  types?: string[];
  limit?: number;
  offset?: number;
}): Promise<NotificationListResponse> {
  const { data } = await apiClient.get<NotificationListResponse>("/notifications", {
    params: {
      unread_only: options?.unreadOnly ?? false,
      types: options?.types?.length ? options.types.join(",") : undefined,
      limit: options?.limit ?? 50,
      offset: options?.offset ?? 0,
    },
  });
  return data;
}

export async function markNotificationRead(notificationId: string): Promise<NotificationItem> {
  const { data } = await apiClient.post<NotificationItem>(
    `/notifications/${notificationId}/read`
  );
  return data;
}
