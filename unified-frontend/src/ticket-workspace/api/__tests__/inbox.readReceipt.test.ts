import { beforeEach, describe, expect, it, vi } from "vitest";

import { composeEmail, getMailFeatures, replyToInteraction, saveDraft } from "@tw/api/inbox";

// The read-receipt flag must reach the backend on every send/draft API
// call when ticked — and an ordinary (unticked) request must be exactly
// what it was before the feature existed.

const client = vi.hoisted(() => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));
vi.mock("@tw/api/client", () => client);

beforeEach(() => {
  vi.clearAllMocks();
  client.apiClient.get.mockResolvedValue({ data: { read_receipts_enabled: true } });
  client.apiClient.post.mockResolvedValue({ data: {} });
  client.apiClient.put.mockResolvedValue({ data: {} });
});

describe("getMailFeatures", () => {
  it("reads the backend feature switches", async () => {
    await expect(getMailFeatures()).resolves.toEqual({ read_receipts_enabled: true });
    expect(client.apiClient.get).toHaveBeenCalledWith("/inbox/features");
  });
});

describe("saveDraft (pre-ticket reply draft)", () => {
  it("stores the flag with the draft when ticked", async () => {
    await saveDraft("i1", "msg", ["c@x.com"], [], "<p>msg</p>", true);

    const [path, body] = client.apiClient.put.mock.calls[0];
    expect(path).toBe("/inbox/i1/draft");
    expect(body.read_receipt_requested).toBe(true);
  });

  it("an unticked draft's body is unchanged (no flag key)", async () => {
    await saveDraft("i1", "msg", [], [], "<p>msg</p>");
    await saveDraft("i1", "msg", [], [], "<p>msg</p>", false);

    for (const [, body] of client.apiClient.put.mock.calls) {
      expect("read_receipt_requested" in body).toBe(false);
      expect(body).toEqual({ message: "msg", cc: [], bcc: [], body_html: "<p>msg</p>" });
    }
  });
});

describe("composeEmail", () => {
  const base = { clientId: "c1", toEmail: "a@x.com", subject: "s", message: "m" };

  it("appends the flag to the form when ticked", async () => {
    await composeEmail({ ...base, readReceiptRequested: true });

    const form = client.apiClient.post.mock.calls[0][1] as FormData;
    expect(client.apiClient.post.mock.calls[0][0]).toBe("/inbox/compose");
    expect(form.get("read_receipt_requested")).toBe("true");
  });

  it("an ordinary compose form has no flag field at all", async () => {
    await composeEmail(base);
    await composeEmail({ ...base, readReceiptRequested: false });

    for (const call of client.apiClient.post.mock.calls) {
      expect((call[1] as FormData).has("read_receipt_requested")).toBe(false);
    }
  });
});

describe("replyToInteraction (pre-ticket reply)", () => {
  it("forwards the request untouched, flag included when the caller set it", async () => {
    const payload = { message: "m", read_receipt_requested: true };
    await replyToInteraction("i1", payload);

    expect(client.apiClient.post).toHaveBeenCalledWith("/inbox/i1/reply", payload);
  });
});
