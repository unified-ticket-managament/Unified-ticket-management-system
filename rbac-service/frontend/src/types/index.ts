export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface AuthUser {
  user_id: string;
  name: string;
  email: string;
  role: string;
  role_id: string;
  is_active: boolean;
  permissions: string[];
}

export interface User {
  user_id: string;
  name: string;
  email: string;
  role_id: string;
  manager_id: string | null;
  teamlead_id: string | null;
  category_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Role {
  role_id: string;
  name: string;
}

// Work-specialization category (Eligibility, AR, Claims, ...) — Staff
// and Team Lead users each belong to exactly one, used to filter/
// assign tickets by the category a user works.
export interface Category {
  category_id: string;
  category_name: string;
}

export interface Permission {
  permission_id: string;
  permission_name: string;
  description: string | null;
  created_at: string;
}

export interface AuditLog {
  audit_log_id: string;
  user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  old_value: string | null;
  new_value: string | null;
  ip_address: string | null;
  user_agent: string | null;
  timestamp: string;
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
  manager_id?: string | null;
  teamlead_id?: string | null;
  category_id?: string | null;
}

export interface RoleForm {
  name: string;
}

export interface CategoryForm {
  category_name: string;
}

export interface ProfileForm {
  name?: string;
  email?: string;
  password?: string;
  current_password?: string;
}

export interface OrganizationNode {
  user_id: string;
  name: string;
  email: string;
  role: string;
  department: string | null;
  is_active: boolean;
  children: OrganizationNode[];
}
