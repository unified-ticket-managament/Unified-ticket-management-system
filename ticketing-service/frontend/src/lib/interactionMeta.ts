import type { InteractionResponse } from "@/types";

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
