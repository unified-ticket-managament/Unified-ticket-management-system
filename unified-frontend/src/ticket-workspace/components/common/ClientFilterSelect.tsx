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
// WorkflowContext's already-cached `clients` list (GET /clients is
// ungated for every role, see that endpoint's own docstring), never a
// separate fetch per page.
//
// Deliberately NOT scoped by Account-Manager ownership (Client.
// account_manager_id) — this used to filter an Account Manager's own
// options down to just their owned clients, but that meant an AM who
// owns zero (or only inactive) clients saw an almost-empty dropdown
// with real company clients missing, while the Mail Inbox's own
// equivalent dropdown (MessageList.tsx) has never applied any such
// scoping and shows every client to every role. Matching that: every
// role sees the same full option list here too. This is UI-only —
// every backend endpoint this selection ultimately feeds into still
// enforces the real per-role visibility scoping server-side
// (account_manager_id-owned-clients conditions, unaffected by this),
// so picking a client outside the caller's own scope just returns an
// empty result, exactly like Mail already behaves for every role.
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
