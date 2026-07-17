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
  override_permissions?: string[];
  scoped_permissions?: Record<string, string[]>;
  date_of_birth?: string | null;
  alternate_email?: string | null;
  phone_number?: string | null;
  office_location?: string | null;
  department?: string | null;
  team?: string | null;
  language?: string | null;
  date_format?: string | null;
  time_format?: string | null;
  time_zone?: string | null;
  default_dashboard?: string | null;
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
  date_of_birth: string | null;
  alternate_email: string | null;
  phone_number: string | null;
  office_location: string | null;
  department: string | null;
  team: string | null;
  language: string | null;
  date_format: string | null;
  time_format: string | null;
  time_zone: string | null;
  default_dashboard: string | null;
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

export interface PermissionOverride {
  override_id: string;
  user_id: string;
  permission_id: string;
  permission_name: string;
  granted_by: string | null;
  reason: string | null;
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  is_active: boolean;
}

export type PermissionRequestStatus = "PENDING" | "APPROVED" | "REJECTED" | "REVOKED";

export interface PermissionRequest {
  request_id: string;
  requester_id: string;
  requester_name: string | null;
  permission_id: string;
  permission_name: string;
  requested_role: string;
  selected_approver_id: string | null;
  selected_approver_name: string | null;
  reason: string;
  scope_ticket_id: string | null;
  status: PermissionRequestStatus;
  reviewed_by: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  expires_at: string | null;
  granted_override_id: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  revoked_by_name: string | null;
  revoke_reason: string | null;
  can_revoke: boolean;
  created_at: string;
}

export interface EligibleApproverUser {
  user_id: string;
  name: string;
  role_name: string;
}

export interface TeammateStaffOption {
  user_id: string;
  name: string;
}

export interface TeammateTicketOption {
  ticket_id: string;
  title: string;
  current_status: string;
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
  date_of_birth?: string | null;
  alternate_email?: string | null;
  phone_number?: string | null;
  office_location?: string | null;
  department?: string | null;
  language?: string | null;
  date_format?: string | null;
  time_format?: string | null;
  time_zone?: string | null;
  default_dashboard?: string | null;
}

export interface OrganizationNode {
  user_id: string;
  name: string;
  email: string;
  role: string;
  department: string | null;
  is_active: boolean;
  // "reports_to" (the real manager_id/teamlead_id line),
  // "reporting_manager" (a dynamic Reporting Manager branch), or
  // "assignable" (the unrestricted company-wide ticket-assignment
  // relationship every Account Manager has with every Team Lead —
  // see root CLAUDE.md's "Organization Structure" section). Optional
  // for back-compat with any cached response predating this field.
  relationship_to_parent?: "reports_to" | "reporting_manager" | "assignable";
  // Category names this node (an Account Manager) is the Reporting
  // Manager for. Always empty for every other role.
  reporting_manager_for?: string[];
  children: OrganizationNode[];
}

export interface ReportingManagerAssignment {
  id: string;
  account_manager_id: string;
  account_manager_name: string;
  category_id: string;
  category_name: string;
  assigned_by: string | null;
  assigned_by_name: string | null;
  assigned_at: string;
}
