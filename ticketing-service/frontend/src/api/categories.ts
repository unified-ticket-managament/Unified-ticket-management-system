import { apiClient } from "./client";
import type { CategoryResponse } from "@/types";

// GET /categories — the work-specialization categories Staff/Team
// Lead users belong to (owned by the RBAC service) — populates the
// ticket-creation category dropdown.
export async function listCategories(): Promise<CategoryResponse[]> {
  const { data } = await apiClient.get<CategoryResponse[]>("/categories");
  return data;
}
