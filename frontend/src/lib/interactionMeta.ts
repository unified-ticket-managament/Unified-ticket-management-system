import type { InteractionResponse } from "@/types";

export interface InteractionTypeMeta {
  icon: string;
  label: string;
  tone: "default" | "success" | "warning" | "danger" | "info" | "accent";
}

export const CONVERSATION_TYPES = ["EMAIL", "INTERNAL_NOTE", "REPLY", "ATTACHMENT"];
export const ACTIVITY_TYPES = ["STATUS_CHANGE", "PRIORITY_CHANGE", "AGENT_TRANSFER"];

const TYPE_META: Record<string, InteractionTypeMeta> = {
  EMAIL: { icon: "📧", label: "Client Email", tone: "accent" },
  INTERNAL_NOTE: { icon: "📝", label: "Internal Note", tone: "warning" },
  REPLY: { icon: "📤", label: "Reply", tone: "success" },
  STATUS_CHANGE: { icon: "⚙", label: "Status Change", tone: "info" },
  PRIORITY_CHANGE: { icon: "🔥", label: "Priority Change", tone: "danger" },
  ATTACHMENT: { icon: "📎", label: "Attachment", tone: "default" },
  AGENT_TRANSFER: { icon: "🔁", label: "Agent Transfer", tone: "info" },
};

export function metaFor(type: string): InteractionTypeMeta {
  return TYPE_META[type] ?? { icon: "•", label: type, tone: "default" };
}

export function summarize(interaction: InteractionResponse): string {
  const payload = interaction.payload ?? {};

  switch (interaction.interaction_type) {
    case "EMAIL":
      return (payload.subject as string) ?? "Email received";
    case "INTERNAL_NOTE":
      return (payload.note as string) ?? "";
    case "REPLY":
      return (payload.message as string) ?? "";
    case "STATUS_CHANGE":
      return `${payload.from ?? "?"} → ${payload.to ?? "?"}`;
    case "PRIORITY_CHANGE":
      return `${payload.from ?? "?"} → ${payload.to ?? "?"}`;
    case "ATTACHMENT":
      return (payload.filename as string) ?? "File uploaded";
    case "AGENT_TRANSFER":
      return `${payload.from_agent_name ?? "Unassigned"} → ${payload.to_agent_name ?? "?"}`;
    default:
      return JSON.stringify(payload);
  }
}
