import type { InteractionResponse } from "@tw/types";

export interface InteractionTypeMeta {
  icon: string;
  label: string;
  tone: "default" | "success" | "warning" | "danger" | "info" | "accent";
}

const TYPE_META: Record<string, InteractionTypeMeta> = {
  EMAIL: { icon: "📧", label: "Client Email", tone: "accent" },
  INTERNAL_NOTE: { icon: "📝", label: "Internal Note", tone: "warning" },
  REPLY: { icon: "📤", label: "Reply", tone: "success" },
  STATUS_CHANGE: { icon: "⚙", label: "Status Change", tone: "info" },
  RESOLVED: { icon: "✅", label: "Ticket Resolved", tone: "success" },
  PRIORITY_CHANGE: { icon: "🔥", label: "Priority Change", tone: "danger" },
  ATTACHMENT: { icon: "📎", label: "Attachment", tone: "default" },
  AGENT_TRANSFER: { icon: "🔁", label: "Agent Assigned", tone: "info" },
  CLAIM: { icon: "🙌", label: "Ticket Claimed", tone: "success" },
  EDIT_ACCESS_REQUESTED: { icon: "🙏", label: "Edit Access Requested", tone: "warning" },
  EDIT_ACCESS_APPROVED: { icon: "🤝", label: "Edit Access Approved", tone: "success" },
  EDIT_ACCESS_REJECTED: { icon: "🚫", label: "Edit Access Rejected", tone: "danger" },
  TICKET_CLOSED: { icon: "🔒", label: "Ticket Closed", tone: "default" },
  TICKET_REOPENED: { icon: "🔓", label: "Ticket Reopened", tone: "info" },
};

export function metaFor(type: string): InteractionTypeMeta {
  return TYPE_META[type] ?? { icon: "•", label: type, tone: "default" };
}

// STATUS_CHANGE/PRIORITY_CHANGE/AGENT_TRANSFER/CLAIM/EDIT_ACCESS_*
// no longer have a real Interaction row of their own — the backend
// synthesizes a display row for them from the ticket's audit trail
// instead (see audit_to_interaction.py), keyed on that audit row's
// own id rather than a real interaction_id. Actions that assume a
// real row exists (Hide) must exclude these types.
export const RETIRED_INTERACTION_TYPES = new Set([
  "STATUS_CHANGE",
  "PRIORITY_CHANGE",
  "AGENT_TRANSFER",
  "CLAIM",
  "EDIT_ACCESS_REQUESTED",
  "EDIT_ACCESS_APPROVED",
  "EDIT_ACCESS_REJECTED",
  "TICKET_CLOSED",
  "TICKET_REOPENED",
]);

export function summarize(interaction: InteractionResponse): string {
  const payload = interaction.payload ?? {};

  switch (interaction.interaction_type) {
    case "EMAIL":
      return interaction.subject || (payload.subject as string) || "Email received";
    case "INTERNAL_NOTE":
      return (payload.note as string) ?? "";
    case "REPLY":
      return (payload.message as string) ?? "";
    case "STATUS_CHANGE":
      return `${payload.from ?? "?"} → ${payload.to ?? "?"}`;
    case "RESOLVED":
      return (payload.resolution_note as string) || "Ticket marked resolved";
    case "PRIORITY_CHANGE":
      return `${payload.from ?? "?"} → ${payload.to ?? "?"}`;
    case "ATTACHMENT": {
      const count = (payload.file_count as number) ?? interaction.attachments?.length ?? 1;
      return `${count} file${count === 1 ? "" : "s"} uploaded`;
    }
    case "AGENT_TRANSFER": {
      const base = `${payload.from_agent_name ?? "Unassigned"} → ${payload.to_agent_name ?? "?"}`;
      return payload.reason ? `${base} (${payload.reason as string})` : base;
    }
    case "CLAIM":
      return `Claimed by ${(payload.agent_name as string) ?? "Unknown"}`;
    case "EDIT_ACCESS_REQUESTED":
      return (payload.reason as string) ?? "Requested edit access";
    case "EDIT_ACCESS_APPROVED":
      return "Edit access approved";
    case "EDIT_ACCESS_REJECTED":
      return (payload.review_note as string) || "Edit access rejected";
    case "TICKET_CLOSED":
      return `Closed by ${(payload.closed_by_name as string) ?? "Unknown"}`;
    case "TICKET_REOPENED":
      return "Ticket reopened";
    default:
      return JSON.stringify(payload);
  }
}

// Per-message direction/sender/body resolvers for a full conversation
// view (the Ticket Details drawer's thread list, and the full-page
// Interaction Details view) — distinct from summarize() above, which
// collapses a single interaction into one summary line rather than
// resolving who it's from and what its body text is.
const MESSAGE_DIRECTION_LABELS: Record<string, string> = {
  EMAIL: "Inbound · Client Email",
  REPLY: "Outbound · Agent Reply",
  INTERNAL_NOTE: "Internal Note",
};

export function messageDirectionLabel(message: InteractionResponse): string {
  return MESSAGE_DIRECTION_LABELS[message.interaction_type] ?? message.direction;
}

export function messageSender(message: InteractionResponse): string | null {
  const payload = message.payload ?? {};
  switch (message.interaction_type) {
    case "EMAIL":
      return (payload.client_name as string) ?? (payload.from_email as string) ?? "Client";
    case "REPLY":
      return message.performed_by_name ?? "Agent";
    case "INTERNAL_NOTE":
      return message.performed_by_name ? `${message.performed_by_name} (internal note)` : null;
    default:
      return message.performed_by_name ?? null;
  }
}

export interface MessageRecipients {
  to: string | null;
  cc: string[];
  bcc: string[];
}

// Outbound replies only — the envelope (to/cc/bcc) is built server-side
// at send time (see build_reply_envelope) and stored under
// payload.envelope, not at the top level of payload alongside `message`.
// Returns null for every other interaction type, and for a REPLY whose
// envelope is absent (a reply sent with no resolvable recipient at all,
// payload.dispatch_status === "NO_RECIPIENT") — there is nothing to show.
export function messageRecipients(message: InteractionResponse): MessageRecipients | null {
  if (message.interaction_type !== "REPLY") return null;
  const envelope = (message.payload as Record<string, unknown> | undefined)?.envelope as
    | Record<string, unknown>
    | undefined;
  if (!envelope) return null;

  return {
    to: (envelope.to_email as string) ?? null,
    cc: (envelope.cc as string[] | undefined) ?? [],
    bcc: (envelope.bcc as string[] | undefined) ?? [],
  };
}

export function messageBody(message: InteractionResponse): string {
  const payload = message.payload ?? {};
  switch (message.interaction_type) {
    case "EMAIL":
      return (payload.body as string) ?? (payload.subject as string) ?? "";
    case "REPLY":
      return (payload.message as string) ?? "";
    case "INTERNAL_NOTE":
      return (payload.note as string) ?? "";
    default:
      return summarize(message);
  }
}
