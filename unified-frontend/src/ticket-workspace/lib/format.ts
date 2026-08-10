export function shortId(id: string, length = 8): string {
  return id.length > length ? `${id.slice(0, length)}…` : id;
}

// The permanent, human-readable ticket reference — "TKT-01", "TKT-27",
// "TKT-104" (padStart only enforces a *minimum* width, so this never
// truncates a larger number). Never derive this from ticket_id/sort
// order/array index — always use the ticket's own real ticket_number.
export function formatTicketNumber(ticketNumber: number): string {
  return `TKT-${String(ticketNumber).padStart(2, "0")}`;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
