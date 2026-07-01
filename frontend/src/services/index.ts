import api, { clearTokens, setTokens } from "@/lib/api";
import {
  AuditLog,
  AuthUser,
  LoginForm,
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

  logout: async (refreshToken?: string) => {
    try {
      await api.post(
        "/auth/logout",
        refreshToken
          ? { refresh_token: refreshToken }
          : {}
      );
    } finally {
      clearTokens();
    }
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
};

/* -------------------------------------------------------------------------- */
/*                                  ROLES                                     */
/* -------------------------------------------------------------------------- */

export const roleService = {
  list: async () => {
    const response = await api.get("/roles");

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
/*                               PERMISSIONS                                  */
/* -------------------------------------------------------------------------- */

export const permissionService = {
  list: async () => {
    const response = await api.get(
      "/permissions"
    );

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
};