import { apiClient } from "./client";

// RBAC's own endpoints (`/api/v1/users`, `/api/v1/roles`) — same
// unified backend Ticketing already talks to, just under the prefix
// RBAC's own routes use instead of Ticketing's unprefixed ones. Reused
// as-is (read-only, no new backend surface) to populate the Internal
// Note "To" dropdown with real users grouped by role, rather than
// hardcoding names.

export interface RbacUserSummary {
  user_id: string;
  name: string;
  email: string;
  role_id: string;
  is_active: boolean;
}

export interface RbacRoleSummary {
  role_id: string;
  name: string;
}

export async function listRbacUsers(): Promise<RbacUserSummary[]> {
  const { data } = await apiClient.get<{ users: RbacUserSummary[]; total: number }>(
    "/api/v1/users",
    { params: { page: 1, page_size: 100 } }
  );
  return data.users;
}

export async function listRbacRoles(): Promise<RbacRoleSummary[]> {
  const { data } = await apiClient.get<{ roles: RbacRoleSummary[]; total: number }>(
    "/api/v1/roles"
  );
  return data.roles;
}
