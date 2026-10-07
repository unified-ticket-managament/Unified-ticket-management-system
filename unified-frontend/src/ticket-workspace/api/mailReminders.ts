import { apiClient } from "@tw/api/client";

// Personal "Remind me" reminders (backend: unified-backend
// app/ticketing/api/mail_reminder.py). A reminder belongs to the
// signed-in user and one mail thread; the server derives the owner from
// the auth token, so no user id is ever sent. `remind_at` is always sent
// as an ISO-8601 instant WITH an offset (Date#toISOString → "…Z").
//
// Errors: apiClient's response interceptor already turns a backend
// `{detail}` body into `Error(detail)`, so callers can show `err.message`.

export type MailReminderStatus = "ACTIVE" | "FIRED" | "DISMISSED" | "CANCELED";

export interface MailReminder {
  reminder_id: string;
  // Always the thread ROOT interaction id.
  interaction_id: string;
  remind_at: string;
  status: MailReminderStatus;
  snooze_count: number;
  fired_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type SnoozeTarget = { remind_at: string } | { minutes: number };

// POST /mail-reminders
export async function createReminder(
  interactionId: string,
  remindAt: Date
): Promise<MailReminder> {
  const { data } = await apiClient.post<MailReminder>("/mail-reminders", {
    interaction_id: interactionId,
    remind_at: remindAt.toISOString(),
  });
  return data;
}

// GET /mail-reminders?status=&interaction_id= — the caller's own only.
export async function getReminders(params?: {
  status?: MailReminderStatus;
  interactionId?: string;
}): Promise<MailReminder[]> {
  const { data } = await apiClient.get<MailReminder[]>("/mail-reminders", {
    params: {
      status: params?.status,
      interaction_id: params?.interactionId,
    },
  });
  return data;
}

// GET /mail-reminders/{id}
export async function getReminder(reminderId: string): Promise<MailReminder> {
  const { data } = await apiClient.get<MailReminder>(
    `/mail-reminders/${reminderId}`
  );
  return data;
}

// PATCH /mail-reminders/{id} — only an ACTIVE reminder can be edited.
export async function updateReminder(
  reminderId: string,
  remindAt: Date
): Promise<MailReminder> {
  const { data } = await apiClient.patch<MailReminder>(
    `/mail-reminders/${reminderId}`,
    { remind_at: remindAt.toISOString() }
  );
  return data;
}

// DELETE /mail-reminders/{id} — cancels (the row is kept server-side).
export async function cancelReminder(reminderId: string): Promise<void> {
  await apiClient.delete(`/mail-reminders/${reminderId}`);
}

// POST /mail-reminders/{id}/snooze — back to ACTIVE at a new time.
export async function snoozeReminder(
  reminderId: string,
  target: SnoozeTarget
): Promise<MailReminder> {
  const { data } = await apiClient.post<MailReminder>(
    `/mail-reminders/${reminderId}/snooze`,
    target
  );
  return data;
}

// POST /mail-reminders/{id}/dismiss — acknowledge a FIRED reminder.
export async function dismissReminder(
  reminderId: string
): Promise<MailReminder> {
  const { data } = await apiClient.post<MailReminder>(
    `/mail-reminders/${reminderId}/dismiss`
  );
  return data;
}
