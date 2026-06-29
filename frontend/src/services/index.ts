import api, { clearTokens, setTokens } from "@/lib/api";
import {
  AuditLog,
  AuthUser,
  LoginForm,
  PaginatedResponse,
  Permission,
  ProfileForm,
  Role,
  RoleForm,
  TokenResponse,
  User,
  UserForm,
} from "@/types";

export const authService = {
  login: async (data: LoginForm) => {
    const response = await api.post<TokenResponse>("/auth/login", data);
    setTokens(response.data.access_token, response.data.refresh_token);
    return response.data;
  },
  logout: async (refreshToken?: string) => {
    try {
      await api.post("/auth/logout", refreshToken ? { refresh_token: refreshToken } : {});
    } finally {
      clearTokens();
    }
  },
  me: async () => {
    const response = await api.get<AuthUser>("/auth/me");
    return response.data;
  },
  updateProfile: async (data: ProfileForm) => {
    const response = await api.patch<User>("/auth/me", data);
    return response.data;
  },
};

export const userService = {
  list: async (params?: Record<string, string | number | boolean | undefined>) => {
    const response = await api.get<PaginatedResponse<User>>("/users", { params });
    return response.data;
  },
  get: async (id: string) => {
    const response = await api.get<User>(`/users/${id}`);
    return response.data;
  },
  create: async (data: UserForm) => {
    const response = await api.post<User>("/users", data);
    return response.data;
  },
  update: async (id: string, data: Partial<UserForm>) => {
    const response = await api.patch<User>(`/users/${id}`, data);
    return response.data;
  },
  delete: async (id: string) => {
    await api.delete(`/users/${id}`);
  },
};

export const roleService = {
  list: async () => {
    const response = await api.get<Role[]>("/roles");
    return response.data;
  },
  create: async (data: RoleForm) => {
    const response = await api.post<Role>("/roles", data);
    return response.data;
  },
  update: async (id: string, data: Partial<RoleForm>) => {
    const response = await api.patch<Role>(`/roles/${id}`, data);
    return response.data;
  },
  delete: async (id: string) => {
    await api.delete(`/roles/${id}`);
  },
};

export const permissionService = {
  list: async () => {
    const response = await api.get<Permission[]>("/permissions");
    return response.data;
  },
  getRolePermissions: async (roleId: string) => {
    const response = await api.get<Permission[]>(`/roles/${roleId}/permissions`);
    return response.data;
  },
  updateRolePermissions: async (roleId: string, permissionIds: string[]) => {
    const response = await api.patch<Permission[]>(`/roles/${roleId}/permissions`, {
      permission_ids: permissionIds,
    });
    return response.data;
  },
};

export const auditService = {
  list: async (params?: Record<string, string | number | undefined>) => {
    const response = await api.get<PaginatedResponse<AuditLog>>("/audit-logs", { params });
    return response.data;
  },
};
