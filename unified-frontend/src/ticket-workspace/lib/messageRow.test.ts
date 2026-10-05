// Run with: npm test  (Node's built-in runner; this module is pure).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { rowClientLabel, rowSender, rowSubject, readToggleLabel } from "./messageRow.ts";
import { buildMessageMenu, type MessageActionPermissions } from "./messageActions.ts";

const NONE: MessageActionPermissions = {
  replyExternal: false,
  createTicket: false,
  attachToTicket: false,
  archive: false,
  moveToFolder: false,
};

describe("rowSender", () => {
  it("prefers latest sender, then from_email, then a fallback", () => {
    assert.equal(rowSender({ latest_sender: "Asha", from_email: "a@x.com" }), "Asha");
    assert.equal(rowSender({ latest_sender: null, from_email: "noreply@kred.com" }), "noreply@kred.com");
    assert.equal(rowSender({ latest_sender: " ", from_email: "" }), "Unknown sender");
  });
});

describe("rowSubject", () => {
  it("falls back to (No subject)", () => {
    assert.equal(rowSubject({ subject: "Hello" }), "Hello");
    assert.equal(rowSubject({ subject: "  " }), "(No subject)");
    assert.equal(rowSubject({ subject: null }), "(No subject)");
  });
});

describe("rowClientLabel", () => {
  it("keeps the client as secondary metadata, category for category mailboxes", () => {
    assert.equal(rowClientLabel({ client_name: "PROBE RCM" }), "PROBE RCM");
    assert.equal(rowClientLabel({ category_id: "c1", category_name: "Billing" }), "Billing");
    assert.equal(rowClientLabel({ category_id: "c1" }), "Category");
  });
});

describe("read toggle quick action", () => {
  it("shares the single-message menu's decision", () => {
    const base = { interaction_id: "1", status: "PENDING", ticket_id: null };
    const unread = buildMessageMenu({ ...base, isUnread: true }, NONE);
    const read = buildMessageMenu({ ...base, isUnread: false }, NONE);
    assert.equal(readToggleLabel(unread.toggleRead), "Mark as read");
    assert.equal(readToggleLabel(read.toggleRead), "Mark as unread");
  });
});

describe("flag / pin quick actions", () => {
  const base = { interaction_id: "1", status: "PENDING", ticket_id: null, isUnread: false };
  it("toggle from the row's own state, needing no extra permission", () => {
    const off = buildMessageMenu(base, NONE);
    assert.equal(off.toggleFlag, "flag");
    assert.equal(off.togglePin, "pin");
    const on = buildMessageMenu({ ...base, is_flagged: true, is_pinned: true }, NONE);
    assert.equal(on.toggleFlag, "unflag");
    assert.equal(on.togglePin, "unpin");
  });
});
