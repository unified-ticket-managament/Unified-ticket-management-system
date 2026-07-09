import { apiClient } from "./client";

export interface NotificationItem {
  notification_id: string;
  notification_type: string;
  title: string;
  message: string;
  link: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  total: number;
  unread_count: number;
  items: NotificationItem[];
}

export async function getNotifications(unreadOnly = false): Promise<NotificationListResponse> {
  const { data } = await apiClient.get<NotificationListResponse>("/notifications", {
    params: { unread_only: unreadOnly, limit: 20 },
  });
  return data;
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await apiClient.post(`/notifications/${notificationId}/read`);
}

export async function markAllNotificationsRead(): Promise<void> {
  await apiClient.post("/notifications/read-all");
}
