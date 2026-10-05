import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  advanceQueue,
  createComposeQueue,
  currentQueueId,
  queueProgressLabel,
} from "./bulkComposeQueue.ts";
import { summarizeBulkResult } from "./bulkResult.ts";
import {
  buildBulkMenu,
  partitionForBulkAction,
  type BulkActionPermissions,
  type MessageActionRow,
} from "./messageActions.ts";
import {
  areAllSelected,
  clearSelection,
  detectPlatform,
  isMultiSelectModifier,
  pruneSelection,
  resolveContextTarget,
  resolveRowClick,
  selectAllVisible,
  selectOnly,
  toggleSelected,
} from "./mailSelection.ts";

const ALL: BulkActionPermissions = {
  replyExternal: true,
  createTicket: true,
  attachToTicket: true,
  archive: true,
  moveToFolder: true,
  hideInteraction: true,
};

function row(id: string, over: Partial<MessageActionRow> = {}): MessageActionRow {
  return { interaction_id: id, status: "PENDING", ticket_id: null, isUnread: true, ...over };
}

describe("selection", () => {
  it("checkbox toggle selects and deselects, never duplicating ids", () => {
    let sel: ReadonlySet<string> = new Set();
    sel = toggleSelected(sel, "a");
    sel = toggleSelected(sel, "b");
    assert.deepEqual([...sel], ["a", "b"]);
    sel = toggleSelected(sel, "a");
    assert.deepEqual([...sel], ["b"]);
    assert.equal(new Set(["a", "a"]).size, 1);
  });

  it("toggling does not mutate the previous selection", () => {
    const before: ReadonlySet<string> = new Set(["a"]);
    toggleSelected(before, "b");
    assert.deepEqual([...before], ["a"]);
  });

  it("Ctrl+Click is the modifier on Windows/Linux, not Cmd", () => {
    assert.equal(isMultiSelectModifier({ ctrlKey: true }, "other"), true);
    assert.equal(isMultiSelectModifier({ metaKey: true }, "other"), false);
    assert.equal(resolveRowClick({ ctrlKey: true }, "other"), "toggle");
    assert.equal(resolveRowClick({}, "other"), "open");
  });

  it("Cmd+Click is the modifier on macOS, not Ctrl", () => {
    assert.equal(isMultiSelectModifier({ metaKey: true }, "mac"), true);
    assert.equal(isMultiSelectModifier({ ctrlKey: true }, "mac"), false);
    assert.equal(resolveRowClick({ metaKey: true }, "mac"), "toggle");
  });

  it("detects the platform", () => {
    assert.equal(detectPlatform({ platform: "MacIntel" }), "mac");
    assert.equal(detectPlatform({ platform: "Win32" }), "other");
    assert.equal(detectPlatform({ userAgent: "X11; Linux x86_64" }), "other");
  });

  it("Ctrl+Click A, C, D builds {A,C,D} without losing earlier picks", () => {
    let sel: ReadonlySet<string> = new Set();
    for (const id of ["A", "C", "D"]) sel = toggleSelected(sel, id);
    assert.deepEqual([...sel], ["A", "C", "D"]);
  });

  it("select all visible, then clear", () => {
    const ids = ["a", "b", "c"];
    const all = selectAllVisible(ids);
    assert.equal(areAllSelected(all, ids), true);
    assert.equal(areAllSelected(toggleSelected(all, "b"), ids), false);
    assert.equal(clearSelection().size, 0);
    assert.equal(areAllSelected(new Set(), []), false);
  });

  it("prune drops ids that left the list and keeps identity when unchanged", () => {
    const sel: ReadonlySet<string> = new Set(["a", "b"]);
    assert.equal(pruneSelection(sel, ["a", "b", "c"]), sel);
    assert.deepEqual([...pruneSelection(sel, ["a"])], ["a"]);
  });

  it("right-click on a selected row preserves the selection and opens the bulk menu", () => {
    const sel: ReadonlySet<string> = new Set(["A", "C", "D"]);
    const target = resolveContextTarget(sel, "C");
    assert.equal(target.kind, "bulk");
    assert.deepEqual([...target.selection], ["A", "C", "D"]);
  });

  it("right-click on an unselected row resets the selection to that row", () => {
    const sel: ReadonlySet<string> = new Set(["A", "C"]);
    const target = resolveContextTarget(sel, "B");
    assert.equal(target.kind, "single");
    assert.deepEqual([...target.selection], ["B"]);
    assert.deepEqual([...selectOnly("B")], ["B"]);
  });

  it("right-click with nothing selected is the single-message menu", () => {
    const target = resolveContextTarget(new Set(), "A");
    assert.equal(target.kind, "single");
    assert.deepEqual([...target.selection], ["A"]);
  });
});

describe("bulk menu eligibility", () => {
  it("restore follows delete's permission gate", () => {
    assert.equal(buildBulkMenu([row("a")], ALL).restore, true);
    assert.equal(buildBulkMenu([row("a")], { ...ALL, hideInteraction: false }).restore, false);
  });

  it("offers only actions the user may perform", () => {
    const menu = buildBulkMenu([row("a")], { ...ALL, archive: false, hideInteraction: false });
    assert.equal(menu.archive, false);
    assert.equal(menu.delete, false);
    assert.equal(menu.reply, true);
  });

  it("hides ticket actions when every selected row is already ticketed", () => {
    const menu = buildBulkMenu([row("a", { ticket_id: "t1" })], ALL);
    assert.equal(menu.createTicket, false);
    assert.equal(menu.linkTicket, false);
    assert.equal(menu.archive, false);
  });

  it("mixed read state offers both mark read and mark unread", () => {
    const menu = buildBulkMenu([row("a", { isUnread: true }), row("b", { isUnread: false })], ALL);
    assert.equal(menu.markRead, true);
    assert.equal(menu.markUnread, true);
  });

  it("synthetic rows are never eligible", () => {
    const menu = buildBulkMenu(
      [row("otp-forward:1"), row("d", { is_compose_draft: true })],
      ALL
    );
    assert.equal(menu.reply, false);
    assert.equal(menu.markRead, false);
  });

  it("partition reports non-eligible rows as skipped instead of dropping them", () => {
    const rows = [row("a"), row("b", { ticket_id: "t" }), row("c")];
    const { eligibleIds, skippedIds } = partitionForBulkAction("createTicket", rows, ALL);
    assert.deepEqual(eligibleIds, ["a", "c"]);
    assert.deepEqual(skippedIds, ["b"]);
  });

  it("a user without the permission gets no ticket actions on OTP rows", () => {
    const perms = { ...ALL, createTicket: false, attachToTicket: false };
    const { eligibleIds, skippedIds } = partitionForBulkAction(
      "linkTicket",
      [row("otp1"), row("otp2")],
      perms
    );
    assert.deepEqual(eligibleIds, []);
    assert.deepEqual(skippedIds, ["otp1", "otp2"]);
  });
});

describe("bulk compose queue", () => {
  it("processes each selected message independently, in order", () => {
    let q = createComposeQueue("replyAll", ["a", "b", "c"]);
    assert.ok(q);
    const seen: string[] = [];
    while (q) {
      seen.push(currentQueueId(q));
      q = advanceQueue(q);
    }
    assert.deepEqual(seen, ["a", "b", "c"]);
  });

  it("each step targets exactly one interaction — ids are never merged", () => {
    const q = createComposeQueue("forward", ["a", "b"]);
    assert.ok(q);
    assert.equal(typeof currentQueueId(q), "string");
    assert.equal(queueProgressLabel(q), "Message 1 of 2");
  });

  it("de-duplicates and returns null for an empty queue", () => {
    assert.deepEqual(createComposeQueue("reply", ["a", "a", "b"])?.ids, ["a", "b"]);
    assert.equal(createComposeQueue("reply", []), null);
  });

  it("keeps ineligible rows as skipped", () => {
    assert.deepEqual(createComposeQueue("reply", ["a"], ["z"])?.skippedIds, ["z"]);
  });
});

describe("bulk result summary", () => {
  it("4 succeeded + 1 failed reads as partial success and keeps the failure selected", () => {
    const s = summarizeBulkResult({
      requested: 5,
      succeeded: 4,
      failed: 1,
      results: [
        { interaction_id: "1", status: "success" },
        { interaction_id: "2", status: "success" },
        { interaction_id: "3", status: "success" },
        { interaction_id: "4", status: "success" },
        { interaction_id: "5", status: "failed", reason: "Not available." },
      ],
    });
    assert.equal(s.message, "4 actions completed. 1 message could not be processed.");
    assert.equal(s.tone, "info");
    assert.deepEqual(s.remainingIds, ["5"]);
  });

  it("all succeeded leaves nothing selected", () => {
    const s = summarizeBulkResult({
      requested: 1,
      succeeded: 1,
      failed: 0,
      results: [{ interaction_id: "1", status: "success" }],
    });
    assert.equal(s.message, "1 action completed.");
    assert.equal(s.tone, "success");
    assert.deepEqual(s.remainingIds, []);
  });

  it("client-skipped rows are reported and stay selected", () => {
    const s = summarizeBulkResult(
      {
        requested: 1,
        succeeded: 1,
        failed: 0,
        results: [{ interaction_id: "1", status: "success" }],
      },
      ["9"]
    );
    assert.match(s.message, /1 message was not eligible and skipped/);
    assert.deepEqual(s.remainingIds, ["9"]);
    assert.equal(s.tone, "info");
  });

  it("everything failed is an error", () => {
    const s = summarizeBulkResult({
      requested: 2,
      succeeded: 0,
      failed: 2,
      results: [
        { interaction_id: "1", status: "failed" },
        { interaction_id: "2", status: "failed" },
      ],
    });
    assert.equal(s.tone, "error");
  });
});

describe("bulk flag / pin eligibility", () => {
  it("offers Flag for unflagged rows and Unflag for flagged ones, independently of pin", () => {
    const menu = buildBulkMenu(
      [row("a", { is_flagged: true, is_pinned: false }), row("b", { is_flagged: false, is_pinned: true })],
      { ...ALL, archive: false, hideInteraction: false }
    );
    assert.equal(menu.flag, true);
    assert.equal(menu.unflag, true);
    assert.equal(menu.pin, true);
    assert.equal(menu.unpin, true);
  });

  it("is idempotent: already-flagged rows are skipped, not failed", () => {
    const rows = [row("a", { is_flagged: true }), row("b"), row("c")];
    const { eligibleIds, skippedIds } = partitionForBulkAction("flag", rows, ALL);
    assert.deepEqual(eligibleIds, ["b", "c"]);
    assert.deepEqual(skippedIds, ["a"]);
  });

  it("needs no permission beyond seeing the mail", () => {
    const none = { ...ALL, archive: false, moveToFolder: false, hideInteraction: false, replyExternal: false };
    const menu = buildBulkMenu([row("a")], none);
    assert.equal(menu.flag, true);
    assert.equal(menu.pin, true);
  });
});
