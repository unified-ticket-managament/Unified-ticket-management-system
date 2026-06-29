export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: string;
  role_id: string;
  permissions: string[];
  is_active: boolean;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  role?: Role;
}

export interface Role {
  id: string;
  name: string;
  description?: string | null;
  created_at?: string;
}

export interface Permission {
  id: string;
  permission_name: string;
  description?: string | null;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  old_value: string | null;
  new_value: string | null;
  timestamp: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface LoginForm {
  email: string;
  password: string;
}

export interface UserForm {
  name: string;
  email: string;
  password?: string;
  role_id: string;
  is_active: boolean;
}

export interface RoleForm {
  name: string;
  description?: string;
}

export interface ProfileForm {
  name?: string;
  email?: string;
  password?: string;
  current_password?: string;
}
