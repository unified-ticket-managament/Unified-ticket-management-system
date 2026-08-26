import api, { clearTokens, setTokens } from "@/lib/api";
import {
  AuditLog,
  AuthUser,
  CategoryForm,
  CategoryMember,
  EligibleApproverUser,
  ImpersonationStartResponse,
  LoginForm,
  OrganizationNode,
  Permission,
  PermissionOverride,
  PermissionRequest,
  ProfileForm,
  ReportingManagerAssignment,
  Role,
  RoleForm,
  TeammateStaffOption,
  TeammateTicketOption,
  TokenResponse,
  User,
  UserForm,
} from "@/types";

/* -------------------------------------------------------------------------- */
/*                                  AUTH                                      */
/* -------------------------------------------------------------------------- */

export const authService = {
  login: async (data: LoginForm) => {
    const response = await api.post<TokenResponse>("/auth/login", data);

    setTokens(
      response.data.access_token,
      response.data.refresh_token
    );

    return response.data;
  },

  logout: () => {
    // Best-effort audit-trail write — fired before clearing tokens
    // (so the auth header is still valid) but never awaited, since
    // logout must always succeed locally even if this request fails.
    api.post("/auth/logout").catch(() => {});
    clearTokens();
  },

  me: async (): Promise<AuthUser> => {
    const response = await api.get<AuthUser>("/auth/me");

    return {
      ...response.data,
      permissions: response.data.permissions ?? [],
      scoped_permissions: response.data.scoped_permissions ?? {},
    };
  },

  updateProfile: async (data: ProfileForm) => {
    const response = await api.patch<User>(
      "/auth/me",
      data
    );

    return response.data;
  },

  changePassword: async (data: { old_password: string; new_password: string }) => {
    const response = await api.post<{ message: string }>(
      "/auth/change-password",
      data
    );

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                    IMPERSONATION ("LOGIN AS USER")                         */
/* -------------------------------------------------------------------------- */

export const impersonationService = {
  start: async (targetUserId: string) => {
    const response = await api.post<ImpersonationStartResponse>(
      "/admin/impersonation/start",
      { target_user_id: targetUserId }
    );

    return response.data;
  },

  // Must be called while the impersonation-shaped access token (from
  // start() above) is the one currently attached — see
  // store/impersonation-store.ts, which calls this before restoring
  // the admin's own original tokens.
  end: async () => {
    const response = await api.post<{ message: string }>(
      "/admin/impersonation/end"
    );

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                                  USERS                                     */
/* -------------------------------------------------------------------------- */

export const userService = {
  list: async (
    params?: Record<
      string,
      string | number | boolean | undefined
    >
  ) => {
    const response = await api.get("/users", {
      params,
    });

    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(`/users/${id}`);

    return response.data;
  },

  create: async (data: UserForm) => {
    const response = await api.post(
      "/users",
      data
    );

    return response.data;
  },

  update: async (
    id: string,
    data: Partial<UserForm>
  ) => {
    const response = await api.put(
      `/users/${id}`,
      data
    );

    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(`/users/${id}`);
  },

  resetPassword: async (id: string, new_password: string) => {
    const response = await api.post<{ message: string }>(
      `/users/${id}/reset-password`,
      { new_password }
    );

    return response.data;
  },

  activate: async (id: string) => {
    const response = await api.patch<User>(`/users/${id}/activate`);

    return response.data;
  },

  deactivate: async (id: string) => {
    const response = await api.patch<User>(`/users/${id}/deactivate`);

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                               ORGANIZATION                                 */
/* -------------------------------------------------------------------------- */

export const organizationService = {
  getMyChart: async (): Promise<OrganizationNode> => {
    const response = await api.get<OrganizationNode>(
      "/users/me/organization-chart"
    );

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                           REPORTING MANAGERS                               */
/* -------------------------------------------------------------------------- */

export const reportingManagerService = {
  list: async (
    filters?: { accountManagerId?: string; categoryId?: string }
  ): Promise<ReportingManagerAssignment[]> => {
    const params = filters?.categoryId
      ? { category_id: filters.categoryId }
      : filters?.accountManagerId
      ? { account_manager_id: filters.accountManagerId }
      : undefined;

    const response = await api.get<{ items: ReportingManagerAssignment[] }>(
      "/reporting-managers",
      { params }
    );

    return response.data.items;
  },

  assign: async (data: {
    account_manager_id: string;
    category_id: string;
  }): Promise<ReportingManagerAssignment> => {
    const response = await api.post<ReportingManagerAssignment>(
      "/reporting-managers",
      data
    );

    return response.data;
  },

  revoke: async (id: string): Promise<void> => {
    await api.delete(`/reporting-managers/${id}`);
  },
};

/* -------------------------------------------------------------------------- */
/*                                  ROLES                                     */
/* -------------------------------------------------------------------------- */

export const roleService = {
  list: async (
    params?: Record<string, string | number | undefined>
  ) => {
    const response = await api.get("/roles", { params });

    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(`/roles/${id}`);

    return response.data;
  },

  create: async (data: RoleForm) => {
    const response = await api.post(
      "/roles",
      data
    );

    return response.data;
  },

  update: async (
    id: string,
    data: Partial<RoleForm>
  ) => {
    const response = await api.put(
      `/roles/${id}`,
      data
    );

    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(`/roles/${id}`);
  },

  // Every active user holding this role, company-wide — deliberately
  // NOT hierarchy-scoped, unlike userService.list(). Backs the Roles
  // page's "Assigned Users" panel and per-role counts only; gated
  // server-side to Super Admin/Site Lead/Account Manager (see
  // unified-backend's access_control.ensure_can_view_full_role_
  // population) regardless of who calls it.
  getUsersForRole: async (roleId: string): Promise<User[]> => {
    const response = await api.get(`/roles/${roleId}/users`);

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                               CATEGORIES                                   */
/* -------------------------------------------------------------------------- */

export const categoryService = {
  list: async (
    params?: Record<string, string | number | undefined>
  ) => {
    const response = await api.get("/categories", { params });

    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(`/categories/${id}`);

    return response.data;
  },

  create: async (data: CategoryForm) => {
    const response = await api.post(
      "/categories",
      data
    );

    return response.data;
  },

  update: async (
    id: string,
    data: Partial<CategoryForm>
  ) => {
    const response = await api.put(
      `/categories/${id}`,
      data
    );

    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(`/categories/${id}`);
  },

  getMembers: async (id: string): Promise<{ members: CategoryMember[] }> => {
    const response = await api.get(`/categories/${id}/members`);

    return response.data;
  },

  setMembers: async (
    id: string,
    userIds: string[]
  ): Promise<{ members: CategoryMember[] }> => {
    const response = await api.put(`/categories/${id}/members`, {
      user_ids: userIds,
    });

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                               PERMISSIONS                                  */
/* -------------------------------------------------------------------------- */

export const permissionService = {
  list: async (
    params?: Record<string, string | number | undefined>
  ) => {
    const response = await api.get("/permissions", {
      params,
    });

    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(
      `/permissions/${id}`
    );

    return response.data;
  },

  create: async (data: any) => {
    const response = await api.post(
      "/permissions",
      data
    );

    return response.data;
  },

  update: async (
    id: string,
    data: any
  ) => {
    const response = await api.put(
      `/permissions/${id}`,
      data
    );

    return response.data;
  },

  delete: async (id: string) => {
    await api.delete(
      `/permissions/${id}`
    );
  },

  getRolePermissions: async (
    roleId: string
  ) => {
    const response = await api.get(
      `/roles/${roleId}/permissions`
    );

    return response.data;
  },

  updateRolePermissions: async (
    roleId: string,
    permissionIds: string[]
  ) => {
    const response = await api.put(
      `/roles/${roleId}/permissions`,
      {
        permission_ids: permissionIds,
      }
    );

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                        PERSONAL PERMISSION OVERRIDES                       */
/* -------------------------------------------------------------------------- */

export const permissionOverrideService = {
  list: async (
    userId: string,
    includeRevoked = false
  ): Promise<PermissionOverride[]> => {
    const response = await api.get<PermissionOverride[]>(
      `/users/${userId}/permission-overrides`,
      { params: { include_revoked: includeRevoked } }
    );

    return response.data;
  },

  grant: async (
    userId: string,
    data: { permission_id: string; reason?: string; expires_at?: string | null }
  ): Promise<PermissionOverride> => {
    const response = await api.post<PermissionOverride>(
      `/users/${userId}/permission-overrides`,
      data
    );

    return response.data;
  },

  revoke: async (userId: string, overrideId: string): Promise<void> => {
    await api.delete(`/users/${userId}/permission-overrides/${overrideId}`);
  },
};

/* -------------------------------------------------------------------------- */
/*                            PERMISSION REQUESTS                             */
/* -------------------------------------------------------------------------- */

export const permissionRequestService = {
  eligiblePermissions: async (): Promise<Permission[]> => {
    const response = await api.get<Permission[]>(
      "/permission-requests/eligible-permissions"
    );

    return response.data;
  },

  eligibleApproverUsers: async (permissionId: string): Promise<EligibleApproverUser[]> => {
    const response = await api.get<EligibleApproverUser[]>(
      "/permission-requests/eligible-approver-users",
      { params: { permission_id: permissionId } }
    );

    return response.data;
  },

  create: async (data: {
    permission_id: string;
    // Optional: a ticket-scoped request against a ticket that already
    // has an owner auto-routes to that owner server-side and ignores
    // this field entirely — only a non-ticket-scoped request, or one
    // against a currently-unassigned ticket, actually requires it.
    selected_approver_id?: string | null;
    reason: string;
    scope_ticket_id?: string | null;
  }): Promise<PermissionRequest> => {
    const response = await api.post<PermissionRequest>("/permission-requests", data);

    return response.data;
  },

  staffOptions: async (): Promise<TeammateStaffOption[]> => {
    const response = await api.get<TeammateStaffOption[]>(
      "/permission-requests/scope/staff-options"
    );

    return response.data;
  },

  ticketOptions: async (staffId: string): Promise<TeammateTicketOption[]> => {
    const response = await api.get<TeammateTicketOption[]>(
      "/permission-requests/scope/ticket-options",
      { params: { staff_id: staffId } }
    );

    return response.data;
  },

  mine: async (): Promise<PermissionRequest[]> => {
    const response = await api.get<PermissionRequest[]>("/permission-requests/mine");

    return response.data;
  },

  pendingForReview: async (): Promise<PermissionRequest[]> => {
    const response = await api.get<PermissionRequest[]>(
      "/permission-requests/pending-for-review"
    );

    return response.data;
  },

  history: async (): Promise<PermissionRequest[]> => {
    const response = await api.get<PermissionRequest[]>("/permission-requests/history");

    return response.data;
  },

  approve: async (
    requestId: string,
    data: { expires_at?: string | null; review_comment?: string | null }
  ): Promise<PermissionRequest> => {
    const response = await api.post<PermissionRequest>(
      `/permission-requests/${requestId}/approve`,
      data
    );

    return response.data;
  },

  reject: async (
    requestId: string,
    data: { review_comment?: string | null }
  ): Promise<PermissionRequest> => {
    const response = await api.post<PermissionRequest>(
      `/permission-requests/${requestId}/reject`,
      data
    );

    return response.data;
  },

  revoke: async (
    requestId: string,
    data: { reason?: string | null }
  ): Promise<PermissionRequest> => {
    const response = await api.post<PermissionRequest>(
      `/permission-requests/${requestId}/revoke`,
      data
    );

    return response.data;
  },
};

/* -------------------------------------------------------------------------- */
/*                               AUDIT LOGS                                   */
/* -------------------------------------------------------------------------- */

export const auditService = {
  list: async (
    params?: Record<
      string,
      string | number | undefined
    >
  ) => {
    const response = await api.get(
      "/audit-logs",
      {
        params,
      }
    );

    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(
      `/audit-logs/${id}`
    );

    return response.data;
  },

  getUserLogs: async (userId: string): Promise<AuditLog[]> => {
    const response = await api.get<AuditLog[]>(
      `/audit-logs/user/${userId}`
    );

    return response.data;
  },
};