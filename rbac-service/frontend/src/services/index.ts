import api, { clearTokens, setTokens } from "@/lib/api";
import {
  AuditLog,
  AuthUser,
  CategoryForm,
  LoginForm,
  OrganizationNode,
  Permission,
  ProfileForm,
  Role,
  RoleForm,
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
    clearTokens();
  },

  me: async (): Promise<AuthUser> => {
    const response = await api.get<AuthUser>("/auth/me");

    return {
      ...response.data,
      permissions: response.data.permissions ?? [],
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