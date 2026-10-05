// Display rules for the Outlook-style Mail row. Pure on purpose (no
// React, no path aliases) so it is unit-testable with `node --test`.
//
// Row hierarchy: Sender → Subject → Client · preview. The client name
// stays on the row (UTMS is client-oriented) but is secondary metadata.

export interface RowDisplaySource {
  from_email?: string | null;
  latest_sender?: string | null;
  subject?: string | null;
  client_name?: string | null;
  category_id?: string | null;
  category_name?: string | null;
}

// Existing sender resolution: the latest replier's name when the thread
// has one, otherwise the original sender's address. No new parsing.
export function rowSender(item: RowDisplaySource): string {
  return item.latest_sender?.trim() || item.from_email?.trim() || "Unknown sender";
}

export function rowSubject(item: RowDisplaySource): string {
  return item.subject?.trim() || "(No subject)";
}

// A CATEGORY-mailbox row has no client — category_id is set instead.
export function rowClientLabel(item: RowDisplaySource): string {
  return item.category_id ? item.category_name || "Category" : item.client_name?.trim() || "";
}

// The read/unread quick action reuses the single-message menu's own
// `toggleRead` decision; this only maps it to the tooltip text.
export function readToggleLabel(toggle: "markRead" | "markUnread"): string {
  return toggle === "markRead" ? "Mark as read" : "Mark as unread";
}
