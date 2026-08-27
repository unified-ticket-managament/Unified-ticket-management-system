import { apiClient } from "./client";
import type { CategoryResponse } from "@tw/types";

// GET /categories — the work-specialization categories Staff/Team
// Lead users belong to (owned by the RBAC service) — populates the
// ticket-creation category dropdown, and (merged with Client rows)
// the "All Clients" filter dropdown across Tickets/Interactions/
// Audit Log/Mail.
//
// `mine: true` narrows the list to the categories the calling Account
// Manager is Reporting Manager for (a no-op for every other role) —
// mirrors listClients' own `mine` param. Omitted for every caller
// that should keep seeing every category (Roles page roster, Rules
// engine picker).
export async function listCategories(options?: { mine?: boolean }): Promise<CategoryResponse[]> {
  const { data } = await apiClient.get<CategoryResponse[]>("/categories", {
    params: options?.mine ? { mine: true } : undefined,
  });
  return data;
}
