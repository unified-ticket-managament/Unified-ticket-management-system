// Which actions the per-message "More actions" menu (MessageList row ⋮,
// see MessageActionsMenu.tsx) offers for one inbox row. Pure on
// purpose: the menu is only a new entry point to actions
// MessageDetailsView's toolbar already has, so this mirrors that
// toolbar's own gating (permission + interaction state) — it never
// replaces the backend's checks, which stay the real authorization
// boundary for every one of these actions.

export type MessageActionKey =
  | "reply"
  | "replyAll"
  | "forward"
  | "createTicket"
  | "linkTicket"
  | "archive";

// Actions that need the message's full details (the reading pane's
// own handlers/dialogs) — routed through InboxPage's pending-action
// hand-off rather than re-implemented in the list.
export interface PendingMessageAction {
  interactionId: string;
  action: MessageActionKey;
}

export interface MessageActionRow {
  interaction_id: string;
  status: string;
  ticket_id: string | null;
  // Resolved by the caller (MessageList's isItemUnread) — is_read
  // alone isn't enough, some rows fall back to a client-side Set.
  isUnread: boolean;
  is_compose_draft?: boolean;
  // Personal Flag / Pin (InboxItem's own fields, spread in by callers).
  is_flagged?: boolean;
  is_pinned?: boolean;
}

export interface MessageActionPermissions {
  replyExternal: boolean;
  createTicket: boolean;
  attachToTicket: boolean;
  archive: boolean;
  moveToFolder: boolean;
}

export interface MessageMenuModel {
  reply: boolean;
  replyAll: boolean;
  forward: boolean;
  toggleRead: "markRead" | "markUnread";
  toggleFlag: "flag" | "unflag";
  togglePin: "pin" | "unpin";
  archive: boolean;
  moveToFolder: boolean;
  viewTicket: boolean;
  createTicket: boolean;
  linkTicket: boolean;
}

// Rows with no real thread behind them (Compose drafts, the synthetic
// OTP-forward rows) have nothing to act on.
const SYNTHETIC_ID_PREFIX = "otp-forward:";

export function hasMessageMenu(row: MessageActionRow): boolean {
  if (row.is_compose_draft) return false;
  return !row.interaction_id.startsWith(SYNTHETIC_ID_PREFIX);
}

export function buildMessageMenu(
  row: MessageActionRow,
  perms: MessageActionPermissions
): MessageMenuModel {
  const isTicketed = Boolean(row.ticket_id);
  return {
    reply: perms.replyExternal,
    replyAll: perms.replyExternal,
    forward: true,
    toggleRead: row.isUnread ? "markRead" : "markUnread",
    // Personal marks: no permission beyond being able to see the mail.
    toggleFlag: row.is_flagged ? "unflag" : "flag",
    togglePin: row.is_pinned ? "unpin" : "pin",
    // Same condition as MessageDetailsView's archiveDisabled, but
    // hidden rather than disabled in a menu.
    archive: perms.archive && !isTicketed && row.status === "PENDING",
    moveToFolder: perms.moveToFolder && !isTicketed,
    viewTicket: isTicketed,
    createTicket: !isTicketed && perms.createTicket,
    linkTicket: !isTicketed && perms.attachToTicket,
  };
}

// ---------------------------------------------------------------------
// Bulk selection
//
// The same gating as buildMessageMenu, evaluated across a selection. The
// UI only decides what to OFFER; the backend authorizes every interaction
// again and stays the real boundary. An action is offered when the user
// holds its permission and at least one selected row is eligible — rows
// that are not eligible are reported as "skipped", never silently dropped.
// ---------------------------------------------------------------------

export type BulkActionKey =
  | "reply"
  | "replyAll"
  | "forward"
  | "createTicket"
  | "linkTicket"
  | "archive"
  | "move"
  | "markRead"
  | "markUnread"
  // Personal marks — no permission beyond being able to see the mail.
  | "flag"
  | "unflag"
  | "pin"
  | "unpin"
  | "delete"
  // Trash-only: undoes "delete". Same permission gate as delete.
  | "restore";

export interface BulkActionPermissions extends MessageActionPermissions {
  // ticket:hide_interaction — gates the soft-delete.
  hideInteraction: boolean;
}

export type BulkMenuModel = Record<BulkActionKey, boolean>;

function isRowEligible(
  action: BulkActionKey,
  row: MessageActionRow,
  perms: BulkActionPermissions
): boolean {
  if (!hasMessageMenu(row)) return false;
  const isTicketed = Boolean(row.ticket_id);
  switch (action) {
    case "reply":
    case "replyAll":
      return perms.replyExternal;
    case "forward":
      return true;
    case "createTicket":
      return perms.createTicket && !isTicketed;
    case "linkTicket":
      return perms.attachToTicket && !isTicketed;
    case "archive":
      return perms.archive && !isTicketed && row.status === "PENDING";
    case "move":
      return perms.moveToFolder && !isTicketed;
    case "markRead":
      return row.isUnread;
    case "markUnread":
      return !row.isUnread;
    case "flag":
      return !row.is_flagged;
    case "unflag":
      return Boolean(row.is_flagged);
    case "pin":
      return !row.is_pinned;
    case "unpin":
      return Boolean(row.is_pinned);
    case "delete":
    case "restore":
      return perms.hideInteraction;
  }
}

export const BULK_ACTION_KEYS: readonly BulkActionKey[] = [
  "reply",
  "replyAll",
  "forward",
  "createTicket",
  "linkTicket",
  "archive",
  "move",
  "markRead",
  "markUnread",
  "flag",
  "unflag",
  "pin",
  "unpin",
  "delete",
  "restore",
];

// Splits a selection into the rows an action applies to and the rows it
// does not (so the caller can say "2 skipped" instead of dropping them).
export function partitionForBulkAction(
  action: BulkActionKey,
  rows: readonly MessageActionRow[],
  perms: BulkActionPermissions
): { eligibleIds: string[]; skippedIds: string[] } {
  const eligibleIds: string[] = [];
  const skippedIds: string[] = [];
  for (const row of rows) {
    (isRowEligible(action, row, perms) ? eligibleIds : skippedIds).push(
      row.interaction_id
    );
  }
  return { eligibleIds, skippedIds };
}

export function buildBulkMenu(
  rows: readonly MessageActionRow[],
  perms: BulkActionPermissions
): BulkMenuModel {
  const model = {} as BulkMenuModel;
  for (const action of BULK_ACTION_KEYS) {
    model[action] = rows.some((row) => isRowEligible(action, row, perms));
  }
  return model;
}
