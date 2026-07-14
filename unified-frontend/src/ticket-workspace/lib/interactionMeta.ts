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
    case "AGENT_TRANSFER":
      return `${payload.from_agent_name ?? "Unassigned"} → ${payload.to_agent_name ?? "?"}`;
    case "CLAIM":
      return `Claimed by ${(payload.agent_name as string) ?? "Unknown"}`;
    case "EDIT_ACCESS_REQUESTED":
      return (payload.reason as string) ?? "Requested edit access";
    case "EDIT_ACCESS_APPROVED":
      return "Edit access approved";
    case "EDIT_ACCESS_REJECTED":
      return (payload.review_note as string) || "Edit access rejected";
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
