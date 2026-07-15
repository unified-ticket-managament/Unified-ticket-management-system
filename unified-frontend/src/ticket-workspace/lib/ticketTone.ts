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
  // Same tone as HIGH — this design system has no dedicated "more
  // urgent than danger" tone — but CRITICAL tickets are already
  // visually distinguished further by the escalation flag icon next
  // to this badge (see TicketsListPage.tsx).
  CRITICAL: "danger",
};
