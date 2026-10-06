// Bridge between the app-wide notification stream (an EventSource owned by
// the top navbar, which lives for the whole authenticated session) and the
// Mail workspace. The navbar already keeps ONE Server-Sent-Events
// connection open with token auth, heartbeat and reconnect/backoff; rather
// than open a second connection per tab (browsers cap connections per
// origin), it re-broadcasts the backend's `mail` events here as a window
// CustomEvent, and the Mail hook listens.
//
// A mail event is only an invalidation SIGNAL (ids + timestamp — never
// message content). The Mail hook responds by refetching through the
// normal, RBAC-checked Inbox API.

export const MAIL_EVENT_NAME = "utms:mail-event";

export type MailEventType = "mail.created" | "mail.updated" | "mail.resync";

export interface MailEventDetail {
  type: MailEventType;
  interaction_id?: string;
  thread_id?: string;
  ticket_id?: string | null;
  timestamp?: string;
}

const KNOWN_TYPES: ReadonlySet<string> = new Set(["mail.created", "mail.updated"]);

export function emitMailEvent(detail: MailEventDetail): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<MailEventDetail>(MAIL_EVENT_NAME, { detail }));
}

// Parse the raw `data:` of an SSE `mail` event and re-broadcast it.
// Anything malformed or of an unknown type is ignored.
export function emitMailEventFromSse(data: string): void {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return;
  }
  if (!parsed || typeof parsed !== "object") return;
  const detail = parsed as MailEventDetail;
  if (!KNOWN_TYPES.has(detail.type)) return;
  emitMailEvent(detail);
}

// The stream just RE-connected after a drop: any mail that arrived while
// it was down produced no event, so tell the Mail view to resync once.
export function emitMailResync(): void {
  emitMailEvent({ type: "mail.resync" });
}

export function subscribeMailEvents(listener: (detail: MailEventDetail) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = (event: Event) => listener((event as CustomEvent<MailEventDetail>).detail);
  window.addEventListener(MAIL_EVENT_NAME, handler);
  return () => window.removeEventListener(MAIL_EVENT_NAME, handler);
}
