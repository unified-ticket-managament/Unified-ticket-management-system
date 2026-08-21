import type { ClientResponse } from "@tw/types";

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

// Duck-typed rather than importing the ticket-workspace's own
// `CurrentUser` — this component is also used from the RBAC-native
// shell's Dashboard/Reports pages (outside the embedded workspace's
// own provider tree), which carry the shell's own `AuthUser` type.
// Both types document the same underlying `/auth/me` shape (see
// AuthContext.tsx's own comment), so only the two fields actually
// read here need to line up.
interface ClientFilterCurrentUser {
  role?: string;
  user_id?: string;
}

interface ClientFilterSelectProps {
  clients: ClientResponse[];
  currentUser: ClientFilterCurrentUser | null | undefined;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

// Shared Client filter, reused everywhere a Tickets/Audit-Log/
// Interactions/Dashboard/Reports page needs one — sourced from
// WorkflowContext's already-cached `clients` list (GET /clients is
// ungated for every role, see that endpoint's own docstring), never a
// separate fetch per page.
//
// An Account Manager only ever owns a subset of the company's clients
// (Client.account_manager_id) — narrowed here so their dropdown never
// offers a choice that the backend would just return zero rows for.
// Every other role sees the full list: Team Lead/Staff are scoped by
// category, not client ownership, so narrowing their dropdown would
// be misleading; Site Lead/Super Admin are unrestricted.
export function ClientFilterSelect({
  clients,
  currentUser,
  value,
  onChange,
  className,
}: ClientFilterSelectProps) {
  const options =
    currentUser?.role === "Account Manager"
      ? clients.filter((c) => c.account_manager_id === currentUser.user_id)
      : clients;

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Filter by client"
      className={className ?? selectClass}
    >
      <option value="ALL">All Clients</option>
      {options.map((c) => (
        <option key={c.client_id} value={c.client_id}>
          {c.name}
        </option>
      ))}
    </select>
  );
}
