import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelReminder,
  createReminder,
  dismissReminder,
  getReminder,
  getReminders,
  snoozeReminder,
  updateReminder,
} from "@tw/api/mailReminders";

const { get, post, patch, del } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));
vi.mock("@tw/api/client", () => ({
  apiClient: { get, post, patch, delete: del },
}));

const reminder = { reminder_id: "r1", interaction_id: "i1", status: "ACTIVE" };

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue({ data: reminder });
  post.mockResolvedValue({ data: reminder });
  patch.mockResolvedValue({ data: reminder });
  del.mockResolvedValue({ data: undefined });
});

describe("mail reminder API client", () => {
  it("creates with the interaction id and a UTC ISO instant, and never sends a user id", async () => {
    const when = new Date("2026-10-08T03:30:00.000Z");

    const out = await createReminder("i1", when);

    expect(out).toBe(reminder);
    expect(post).toHaveBeenCalledWith("/mail-reminders", {
      interaction_id: "i1",
      remind_at: "2026-10-08T03:30:00.000Z",
    });
    expect(JSON.stringify(post.mock.calls[0][1])).not.toContain("user_id");
  });

  it("lists with the status / interaction filters", async () => {
    await getReminders({ status: "ACTIVE", interactionId: "i1" });
    expect(get).toHaveBeenCalledWith("/mail-reminders", {
      params: { status: "ACTIVE", interaction_id: "i1" },
    });
  });

  it("lists with no filters", async () => {
    await getReminders();
    expect(get).toHaveBeenCalledWith("/mail-reminders", {
      params: { status: undefined, interaction_id: undefined },
    });
  });

  it("gets one", async () => {
    await getReminder("r1");
    expect(get).toHaveBeenCalledWith("/mail-reminders/r1");
  });

  it("updates the time", async () => {
    await updateReminder("r1", new Date("2026-10-09T09:00:00.000Z"));
    expect(patch).toHaveBeenCalledWith("/mail-reminders/r1", {
      remind_at: "2026-10-09T09:00:00.000Z",
    });
  });

  it("cancels with DELETE", async () => {
    await expect(cancelReminder("r1")).resolves.toBeUndefined();
    expect(del).toHaveBeenCalledWith("/mail-reminders/r1");
  });

  it("snoozes by absolute time or by minutes", async () => {
    await snoozeReminder("r1", { minutes: 60 });
    await snoozeReminder("r1", { remind_at: "2026-10-09T09:00:00.000Z" });
    expect(post).toHaveBeenNthCalledWith(1, "/mail-reminders/r1/snooze", { minutes: 60 });
    expect(post).toHaveBeenNthCalledWith(2, "/mail-reminders/r1/snooze", {
      remind_at: "2026-10-09T09:00:00.000Z",
    });
  });

  it("dismisses", async () => {
    await dismissReminder("r1");
    expect(post).toHaveBeenCalledWith("/mail-reminders/r1/dismiss");
  });

  it("propagates API errors to the caller", async () => {
    post.mockRejectedValueOnce(new Error("remind_at must be in the future."));
    await expect(createReminder("i1", new Date())).rejects.toThrow("in the future");
  });
});
