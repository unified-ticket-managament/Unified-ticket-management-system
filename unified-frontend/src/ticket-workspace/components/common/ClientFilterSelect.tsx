import type { CategoryResponse, ClientResponse } from "@tw/types";
import { mergedClientFilterOptions } from "@tw/lib/clientFilter";

const selectClass =
  "rounded-md2 border border-border bg-surface px-3 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

interface ClientFilterSelectProps {
  clients: ClientResponse[];
  categories: CategoryResponse[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

// Shared Client filter, reused everywhere a Tickets/Audit-Log/
// Interactions/Dashboard/Reports page needs one — sourced from
// WorkflowContext's already-cached `clients`/`categories` lists,
// never a separate fetch per page.
//
// Both `clients` (GET /clients?mine=true) and `categories`
// (GET /categories?mine=true) already arrive pre-scoped to the
// calling Account Manager's own ownership — Client.account_manager_id
// for clients, the reporting_manager_teams mapping for category
// shared inboxes — and unscoped (every client/category) for every
// other role, matching how Mail's own equivalent dropdown
// (MessageList.tsx) already reads from the same two lists. This
// component itself applies no further ownership filtering beyond
// mergedClientFilterOptions' existing is_active/mailbox/name-collision
// merge logic; every backend endpoint this selection ultimately feeds
// into still separately enforces its own real per-role visibility
// scoping server-side, so picking an option outside the caller's own
// scope (not normally offered here anymore) would still just return
// an empty result.
export function ClientFilterSelect({
  clients,
  categories,
  value,
  onChange,
  className,
}: ClientFilterSelectProps) {
  const { activeClients, categoryOptions } = mergedClientFilterOptions(clients, categories);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Filter by client"
      className={className ?? selectClass}
    >
      <option value="ALL">All Clients</option>
      {activeClients.map((c) => (
        <option key={c.client_id} value={c.client_id}>
          {c.name}
        </option>
      ))}
      {categoryOptions.map((c) => (
        <option key={`category-${c.category_id}`} value={c.category_name}>
          {c.category_name}
        </option>
      ))}
    </select>
  );
}
