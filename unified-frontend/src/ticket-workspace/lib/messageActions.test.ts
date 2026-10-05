// Run with: npm test  (Node's built-in runner; this module is pure).
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildMessageMenu,
  hasMessageMenu,
  type MessageActionPermissions,
  type MessageActionRow,
} from "./messageActions.ts";

const ALL: MessageActionPermissions = {
  replyExternal: true,
  createTicket: true,
  attachToTicket: true,
  archive: true,
  moveToFolder: true,
};
const NONE: MessageActionPermissions = {
  replyExternal: false,
  createTicket: false,
  attachToTicket: false,
  archive: false,
  moveToFolder: false,
};
const row = (over: Partial<MessageActionRow> = {}): MessageActionRow => ({
  interaction_id: "i-1",
  status: "PENDING",
  ticket_id: null,
  isUnread: true,
  ...over,
});

describe("hasMessageMenu", () => {
  it("is true for a normal thread row", () => assert.equal(hasMessageMenu(row()), true));
  it("is false for Compose drafts", () =>
    assert.equal(hasMessageMenu(row({ is_compose_draft: true })), false));
  it("is false for synthetic OTP-forward rows", () =>
    assert.equal(hasMessageMenu(row({ interaction_id: "otp-forward:abc" })), false));
});

describe("buildMessageMenu", () => {
  it("offers exactly one contextual read/unread toggle", () => {
    assert.equal(buildMessageMenu(row({ isUnread: true }), ALL).toggleRead, "markRead");
    assert.equal(buildMessageMenu(row({ isUnread: false }), ALL).toggleRead, "markUnread");
  });

  it("hides reply/replyAll without communication:reply_external, keeps forward", () => {
    const m = buildMessageMenu(row(), NONE);
    assert.equal(m.reply, false);
    assert.equal(m.replyAll, false);
    assert.equal(m.forward, true);
  });

  it("offers archive only for a pending, unticketed row with permission", () => {
    assert.equal(buildMessageMenu(row(), ALL).archive, true);
    assert.equal(buildMessageMenu(row(), NONE).archive, false);
    assert.equal(buildMessageMenu(row({ status: "ASSIGNED" }), ALL).archive, false);
    assert.equal(buildMessageMenu(row({ status: "IGNORED" }), ALL).archive, false);
    assert.equal(buildMessageMenu(row({ ticket_id: "t-1" }), ALL).archive, false);
  });

  it("offers Move to only for unticketed rows with permission", () => {
    assert.equal(buildMessageMenu(row(), ALL).moveToFolder, true);
    assert.equal(buildMessageMenu(row(), NONE).moveToFolder, false);
    assert.equal(buildMessageMenu(row({ ticket_id: "t-1" }), ALL).moveToFolder, false);
  });

  it("unticketed rows get Create/Link ticket (permission-gated), never View Ticket", () => {
    const m = buildMessageMenu(row(), ALL);
    assert.deepEqual([m.createTicket, m.linkTicket, m.viewTicket], [true, true, false]);
    const denied = buildMessageMenu(row(), NONE);
    assert.deepEqual([denied.createTicket, denied.linkTicket], [false, false]);
    const onlyLink = buildMessageMenu(row(), { ...NONE, attachToTicket: true });
    assert.deepEqual([onlyLink.createTicket, onlyLink.linkTicket], [false, true]);
  });

  it("ticketed rows get View Ticket and no create/link, regardless of permission", () => {
    const m = buildMessageMenu(row({ ticket_id: "t-1" }), ALL);
    assert.deepEqual([m.viewTicket, m.createTicket, m.linkTicket], [true, false, false]);
  });
});
