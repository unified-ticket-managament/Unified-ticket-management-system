import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { emitMailEvent, emitMailResync } from "@/lib/mail-events";
import { getInbox, getViewCounts } from "@tw/api/inbox";
import { useMailInbox } from "@tw/hooks/useMailInbox";
import type { InboxItem } from "@tw/types";

// The REAL Mail hook with only the network mocked: when the backend says
// mail arrived (a `mail` event over the notification stream), the active
// view updates by itself — no Refresh click — while filters, the open
// email and the composer are left alone, and any failure on this live path
// is invisible and harmless.

vi.mock("@tw/api/inbox", () => ({
  getInbox: vi.fn(),
  getViewCounts: vi.fn(),
  getFolderCounts: vi.fn(),
  getSent: vi.fn(),
  getReplied: vi.fn(),
  getDrafts: vi.fn(),
  openInboxThread: vi.fn(),
  composeEmail: vi.fn(),
  discardDraft: vi.fn(),
  forwardToInternalUser: vi.fn(),
  markInboxRead: vi.fn(),
  markInboxUnread: vi.fn(),
  saveDraft: vi.fn(),
  sendDraft: vi.fn(),
  updateInteractionFolder: vi.fn(),
  updateInteractionTags: vi.fn(),
  uploadDraftAttachment: vi.fn(),
}));
vi.mock("@tw/api/interaction", () => ({ deleteAttachment: vi.fn() }));
vi.mock("@tw/api/mailFolder", () => ({
  createMailFolder: vi.fn(),
  deleteMailFolder: vi.fn(),
  listMailFolders: vi.fn().mockResolvedValue([]),
  moveMailFolder: vi.fn(),
  renameMailFolder: vi.fn(),
}));
vi.mock("@tw/api/notifications", () => ({
  getNotifications: vi.fn().mockResolvedValue({ items: [], unread_count: 0, total: 0 }),
  markNotificationRead: vi.fn(),
}));

const setSelectedEmail = vi.fn();
const pushToast = vi.fn();
let selectedEmail: unknown = null;
vi.mock("@tw/context/WorkflowContext", () => ({
  useWorkflowContext: () => ({
    selectedEmail,
    setSelectedEmail,
    clients: [],
    clientsLoading: false,
    clientsError: false,
    categories: [],
  }),
}));
vi.mock("@tw/context/AuthContext", () => ({
  useAuthContext: () => ({
    currentUser: { user_id: "u1", role: "Account Manager", permissions: [] },
  }),
}));
vi.mock("@tw/context/ToastContext", () => ({ useToast: () => ({ pushToast }) }));

const mail = (id: string): InboxItem =>
  ({
    interaction_id: id,
    open_interaction_id: id,
    client_name: "Acme",
    subject: `Subject ${id}`,
    status: "PENDING",
    is_read: false,
    received_at: "2026-10-06T10:00:00Z",
  }) as unknown as InboxItem;

let serverRows: InboxItem[] = [];

function mockServer() {
  // New mail lands in the "pending" tab; every other tab is empty.
  vi.mocked(getInbox).mockImplementation(async (key: unknown) =>
    key === "pending"
      ? { items: [...serverRows], total: serverRows.length }
      : { items: [], total: 0 }
  );
  vi.mocked(getViewCounts).mockImplementation(
    async () =>
      ({ pending: serverRows.length, replied: 0, ticketed: 0, archived: 0, all: 0 }) as never
  );
}

const ids = (items: InboxItem[]) => items.map((i) => i.interaction_id);
const inboxCalls = () => vi.mocked(getInbox).mock.calls.length;

async function mountLoaded() {
  const hook = renderHook(() => useMailInbox());
  await waitFor(() => expect(ids(hook.result.current.filteredItems)).toEqual(["m1"]));
  return hook;
}

beforeEach(() => {
  vi.clearAllMocks();
  selectedEmail = null;
  serverRows = [mail("m1")];
  mockServer();
});

describe("new mail appears automatically", () => {
  it("shows a newly ingested message with no Refresh click", async () => {
    const hook = await mountLoaded();
    const refresh = vi.spyOn(hook.result.current, "refresh");

    serverRows = [mail("m2"), mail("m1")]; // the backend has ingested it
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));

    await waitFor(() => expect(ids(hook.result.current.filteredItems)).toEqual(["m2", "m1"]), {
      timeout: 3000,
    });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("updates the pending count as well", async () => {
    const hook = await mountLoaded();
    const before = hook.result.current.viewCounts.pending;

    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));

    await waitFor(() => expect(hook.result.current.viewCounts.pending).toBe(before + 1), {
      timeout: 3000,
    });
  });

  it("several quick events cost exactly one refresh and show no duplicate rows", async () => {
    const hook = await mountLoaded();

    // Baseline: what ONE live refresh costs (the Pending view is built from
    // several lists, so one refresh is several getInbox calls).
    let before = inboxCalls();
    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(2), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 700));
    const oneRefreshCost = inboxCalls() - before;
    expect(oneRefreshCost).toBeGreaterThan(0);

    // A burst of five events costs the same single refresh.
    before = inboxCalls();
    serverRows = [mail("m4"), mail("m3"), mail("m2"), mail("m1")];
    act(() => {
      for (const id of ["m2", "m3", "m4", "m4", "m3"]) {
        emitMailEvent({ type: "mail.created", interaction_id: id });
      }
    });
    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(4), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 700));

    expect(new Set(ids(hook.result.current.filteredItems)).size).toBe(4); // no duplicates
    expect(inboxCalls() - before).toBe(oneRefreshCost);
  });

  it("a reply on an existing thread (mail.updated) refreshes the list too", async () => {
    const hook = await mountLoaded();

    serverRows = [{ ...mail("m1"), is_read: false, subject: "Re: Subject m1" } as InboxItem];
    act(() => emitMailEvent({ type: "mail.updated", interaction_id: "m1" }));

    await waitFor(() => expect(hook.result.current.filteredItems[0].subject).toBe("Re: Subject m1"), {
      timeout: 3000,
    });
  });

  it("an SSE reconnect resync catches up on mail missed while disconnected", async () => {
    const hook = await mountLoaded();

    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailResync());

    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(2), { timeout: 3000 });
  });
});

describe("the user's context is preserved", () => {
  it("keeps the active filters on the live refetch", async () => {
    const hook = await mountLoaded();
    act(() => hook.result.current.setPriorityFilter("HIGH"));
    await waitFor(() => {
      const last = vi.mocked(getInbox).mock.calls.at(-1)!;
      expect(last[1]).toMatchObject({ priority: "HIGH" });
    });

    const before = inboxCalls();
    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));

    await waitFor(() => expect(inboxCalls()).toBeGreaterThan(before), { timeout: 3000 });
    const live = vi.mocked(getInbox).mock.calls.at(-1)!;
    expect(live[1]).toMatchObject({ priority: "HIGH" }); // same filter, not reset
    expect(hook.result.current.priorityFilter).toBe("HIGH");
  });

  it("keeps the search text", async () => {
    const hook = await mountLoaded();
    act(() => hook.result.current.setSearch("m1"));
    await waitFor(() => expect(hook.result.current.search).toBe("m1"));

    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    await new Promise((r) => setTimeout(r, 700));

    expect(hook.result.current.search).toBe("m1");
  });

  it("never touches the open email: no thread reload, no selection change", async () => {
    selectedEmail = { interaction_id: "m1", subject: "Open" };
    const hook = await mountLoaded();

    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.updated", interaction_id: "m1" }));
    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(2), { timeout: 3000 });

    const { openInboxThread } = await import("@tw/api/inbox");
    expect(openInboxThread).not.toHaveBeenCalled();
    expect(setSelectedEmail).not.toHaveBeenCalled();
  });

  it("does not show a spinner or a toast for a live update", async () => {
    const hook = await mountLoaded();
    pushToast.mockClear();

    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    // isLoading is the page-level spinner; the live path must not raise it.
    const seen: boolean[] = [];
    const stop = setInterval(() => seen.push(hook.result.current.isLoading), 10);
    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(2), { timeout: 3000 });
    clearInterval(stop);

    expect(seen.some(Boolean)).toBe(false);
    expect(pushToast).not.toHaveBeenCalled();
  });
});

describe("the manual Refresh and failures", () => {
  it("the existing Refresh button path still works", async () => {
    const hook = await mountLoaded();
    const before = inboxCalls();

    serverRows = [mail("m2"), mail("m1")];
    await act(async () => {
      await hook.result.current.refresh();
    });

    expect(inboxCalls()).toBeGreaterThan(before);
    expect(ids(hook.result.current.filteredItems)).toEqual(["m2", "m1"]);
  });

  it("works exactly as before when no event ever arrives (SSE down)", async () => {
    const hook = await mountLoaded();
    await new Promise((r) => setTimeout(r, 600));

    expect(ids(hook.result.current.filteredItems)).toEqual(["m1"]);
    expect(hook.result.current.hasError).toBe(false);
  });

  it("a failing live refetch is invisible: no error state, no toast, list intact", async () => {
    const hook = await mountLoaded();
    pushToast.mockClear();

    vi.mocked(getInbox).mockRejectedValue(new Error("network down"));
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    await new Promise((r) => setTimeout(r, 800));

    expect(ids(hook.result.current.filteredItems)).toEqual(["m1"]);
    expect(hook.result.current.hasError).toBe(false);
    expect(pushToast).not.toHaveBeenCalled();

    // ...and it recovers on the next event.
    mockServer();
    serverRows = [mail("m2"), mail("m1")];
    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    await waitFor(() => expect(hook.result.current.filteredItems).toHaveLength(2), { timeout: 3000 });
  });

  it("unmounting removes the live listener (no refetch after the Mail tab closes)", async () => {
    const hook = await mountLoaded();
    hook.unmount();
    const before = inboxCalls();

    act(() => emitMailEvent({ type: "mail.created", interaction_id: "m2" }));
    await new Promise((r) => setTimeout(r, 800));

    expect(inboxCalls()).toBe(before);
  });
});
