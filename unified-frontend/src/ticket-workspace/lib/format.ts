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

// "Employee Name (266)" for an assignable-user picker option — falls
// back to the bare name when no official employee_number exists (demo/
// system accounts). Never touches the underlying selected value, which
// remains the user's UUID everywhere this is used for display only.
export function formatAssigneeLabel(user: { name: string; employee_number?: string | null }): string {
  return user.employee_number ? `${user.name} (${user.employee_number})` : user.name;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
