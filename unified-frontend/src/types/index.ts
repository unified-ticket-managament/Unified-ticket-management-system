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
  // Display-only Leave indicator (see shared_models.models.User.
  // is_on_leave's own docstring) — never an authorization rule.
  // Optional for back-compat with any cached response predating it.
  is_on_leave?: boolean;
  permissions: string[];
  override_permissions?: string[];
  scoped_permissions?: Record<string, string[]>;
  // Official, human-readable Employee ID from HR master data (e.g.
  // "266") — display/search only, never a relational key. null/absent
  // for accounts with no official employee record.
  employee_number?: string | null;
  date_of_birth?: string | null;
  alternate_email?: string | null;
  phone_number?: string | null;
  office_location?: string | null;
  department?: string | null;
  team?: string | null;
  designation?: string | null;
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
  // Organization-Chart-only reporting relationship — separate from
  // manager_id/teamlead_id above, which keep their existing meaning.
  // Unrestricted by role; see unified-backend's OrganizationService.
  reporting_manager_id: string | null;
  // Legacy "primary category" — kept in sync with the first entry of
  // category_ids below, never a separate source of truth. Prefer
  // category_ids for display/filtering; this stays for back-compat.
  category_id: string | null;
  // Full category membership (many-to-many) — a user (most commonly
  // a Team Lead) may belong to more than one. Optional for back-compat
  // with any cached response predating this field.
  category_ids?: string[];
  // Computed, read-only: does this user hold at least one active
  // Reporting Manager (reporting_manager_teams) assignment for any
  // category — not a Role/permission, just an HR responsibility
  // layered on the Account Manager role. Optional for back-compat
  // with any cached response predating this field.
  is_reporting_manager?: boolean;
  is_active: boolean;
  // Display-only Leave indicator — see shared_models.models.User.
  // is_on_leave's own docstring. Never narrows/filters a user picker;
  // surfaced only as "(Leave)" appended to the name.
  is_on_leave: boolean;
  created_at: string;
  updated_at: string;
  employee_number?: string | null;
  date_of_birth: string | null;
  alternate_email: string | null;
  phone_number: string | null;
  office_location: string | null;
  department: string | null;
  team: string | null;
  designation: string | null;
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
  scope_ticket_number: number | null;
  scope_ticket_title: string | null;
  scope_ticket_owner_id: string | null;
  scope_ticket_owner_name: string | null;
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
  is_on_leave: boolean;
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
  // Display-only Leave indicator, editable from the user detail
  // drawer's own toggle — see the User interface's own doc comment.
  is_on_leave?: boolean;
  manager_id?: string | null;
  teamlead_id?: string | null;
  reporting_manager_id?: string | null;
  category_id?: string | null;
  // Full category selection — takes precedence over category_id when
  // present (see unified-backend's UserService._resolve_category_ids).
  category_ids?: string[];
  // Internal roles only (Super Admin/Site Lead/Account Manager/Team
  // Lead/Staff) — required server-side per role, see
  // unified-backend/app/rbac/services/user_service.py's
  // DESIGNATION_REQUIRED_ROLE_NAMES.
  designation?: string | null;
  alternate_email?: string | null;
  // Internal roles only — required server-side on create, see
  // unified-backend/app/rbac/services/user_service.py's
  // DESIGNATION_REQUIRED_ROLE_NAMES employee_number check.
  employee_number?: string | null;
  // Client role only — full-replace on edit, at least one required on
  // create. Omitted entirely for every other role.
  contact_emails?: string[];
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
  // Self-toggled from the Profile page's own header — see the User
  // interface's own doc comment on is_on_leave.
  is_on_leave?: boolean;
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
  // Every category this node's user belongs to (many-to-many) —
  // additive alongside `department` above, which stays a single
  // joined/first-category string for back-compat. Optional for
  // back-compat with any cached response predating this field.
  departments?: string[];
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
