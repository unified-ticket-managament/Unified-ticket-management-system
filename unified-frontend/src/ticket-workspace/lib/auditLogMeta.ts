import type { AuditEventType } from "@tw/types";

export interface AuditEventMeta {
  icon: string;
  label: string;
  tone: "default" | "success" | "warning" | "danger" | "info" | "accent";
}

const EVENT_META: Record<AuditEventType, AuditEventMeta> = {
  TICKET_CREATED: { icon: "🎫", label: "Ticket Created", tone: "success" },
  TICKET_UPDATED: { icon: "✏️", label: "Ticket Updated", tone: "info" },
  TICKET_RESOLVED: { icon: "✅", label: "Ticket Resolved", tone: "success" },
  STATUS_CHANGED: { icon: "⚙", label: "Status Changed", tone: "info" },
  PRIORITY_CHANGED: { icon: "🔥", label: "Priority Changed", tone: "danger" },
  AGENT_TRANSFERRED: { icon: "🔁", label: "Agent Assigned", tone: "accent" },
  INTERACTION_HIDDEN: { icon: "🙈", label: "Interaction Hidden", tone: "warning" },
  ATTACHMENT_UPLOADED: { icon: "📎", label: "Attachment Uploaded", tone: "default" },
  NOTE_ADDED: { icon: "📝", label: "Note Added", tone: "warning" },
  REPLY_ADDED: { icon: "📤", label: "Reply Added", tone: "success" },
  EMAIL_RECEIVED: { icon: "📧", label: "Email Received", tone: "accent" },
  CLIENT_CREATED: { icon: "🏢", label: "Client Onboarded", tone: "success" },
  TICKET_CLAIMED: { icon: "🙌", label: "Ticket Claimed", tone: "accent" },
  INTERACTION_CLAIMED: { icon: "🙋", label: "Assigned to Me", tone: "accent" },
  INTERACTION_ARCHIVED: { icon: "🗄", label: "Archived", tone: "default" },
  EDIT_ACCESS_REQUESTED: { icon: "🙏", label: "Edit Access Requested", tone: "warning" },
  EDIT_ACCESS_APPROVED: { icon: "🤝", label: "Edit Access Approved", tone: "success" },
  EDIT_ACCESS_REJECTED: { icon: "🚫", label: "Edit Access Rejected", tone: "danger" },
  SLA_MANUALLY_PAUSED: { icon: "⏸", label: "SLA Manually Paused", tone: "warning" },
  SLA_MANUALLY_RESUMED: { icon: "▶", label: "SLA Manually Resumed", tone: "info" },
  SLA_BREACH_DETECTED: { icon: "⚠", label: "SLA Breached", tone: "danger" },
  SLA_ESCALATED: { icon: "🔺", label: "SLA Escalated", tone: "danger" },
<<<<<<< Updated upstream
  ESCALATION_CREATED: { icon: "📣", label: "Escalation Created", tone: "warning" },
  ESCALATION_ACKNOWLEDGED: { icon: "👀", label: "Escalation Acknowledged", tone: "info" },
  ESCALATION_ADVANCED: { icon: "⬆️", label: "Escalation Advanced", tone: "warning" },
  ESCALATION_CLOSED: { icon: "✅", label: "Escalation Closed", tone: "success" },
=======
>>>>>>> Stashed changes
};

export function auditMetaFor(type: AuditEventType): AuditEventMeta {
  return EVENT_META[type] ?? { icon: "•", label: type, tone: "default" };
}

// Bookkeeping keys that ride along in old_values/new_values for
// cross-reference but aren't a meaningful "change" to show in a diff.
const SKIP_KEYS = new Set(["interaction_id", "ticket_id"]);

export interface AuditDiffField {
  key: string;
  from: unknown;
  to: unknown;
}

export function diffFields(
  oldValues: Record<string, unknown> | null,
  newValues: Record<string, unknown> | null
): AuditDiffField[] {
  const keys = new Set([
    ...Object.keys(oldValues ?? {}),
    ...Object.keys(newValues ?? {}),
  ]);

  return Array.from(keys)
    .filter((key) => !SKIP_KEYS.has(key))
    .map((key) => ({
      key,
      from: oldValues?.[key] ?? null,
      to: newValues?.[key] ?? null,
    }));
}

export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function humanizeFieldKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
