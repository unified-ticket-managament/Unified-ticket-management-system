import { api } from "@/lib/api";

// The notifications router lives unprefixed on the unified backend
// (grouped with ticketing's own routes in app/main.py), while this
// app's default `api` instance is baseURL'd to .../api/v1 — override
// baseURL per-call to the un-prefixed root rather than standing up a
// whole second axios instance just for this. Interceptors (auth
// header, 401 refresh) still apply since they're bound to `api`
// itself, not to any particular baseURL.
const API_ROOT = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1").replace(
  /\/api\/v1\/?$/,
  ""
);

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
  const { data } = await api.get<NotificationListResponse>("/notifications", {
    baseURL: API_ROOT,
    params: { unread_only: unreadOnly, limit: 20 },
  });
  return data;
}

export async function markNotificationRead(notificationId: string): Promise<void> {
  await api.post(`/notifications/${notificationId}/read`, null, { baseURL: API_ROOT });
}

export async function markAllNotificationsRead(): Promise<void> {
  await api.post("/notifications/read-all", null, { baseURL: API_ROOT });
}
