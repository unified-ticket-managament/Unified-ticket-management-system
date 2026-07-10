import type { TicketPriority, TicketStatus } from "@tw/types";

type Tone = "default" | "success" | "warning" | "danger" | "info" | "accent";

export const statusTone: Record<TicketStatus, Tone> = {
  OPEN: "accent",
  IN_PROGRESS: "info",
  PENDING: "warning",
  WAITING_FOR_CLIENT: "warning",
  RESOLVED: "success",
  CLOSED: "default",
};

export const priorityTone: Record<TicketPriority, Tone> = {
  LOW: "default",
  MEDIUM: "warning",
  HIGH: "danger",
};
