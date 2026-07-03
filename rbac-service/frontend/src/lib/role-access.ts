import { TranslationKey } from "@/lib/i18n/translations";

export const ROLE_NAMES = {
  SUPER_ADMIN: "Super Admin",
  MANAGER: "Manager",
  TEAM_LEAD: "Team Lead",
  STAFF: "Staff",
  VIEWER: "Viewer",
} as const;

export type NavItemKey =
  | "Dashboard"
  | "Users"
  | "Roles"
  | "Audit Logs"
  | "Create Dummy Mail"
  | "Inbox"
  | "Interactions"
  | "Tickets"
  | "Ticket Audit Log"
  | "Profile"
  | "Settings";

export const NAV_ITEM_TRANSLATION_KEY: Record<NavItemKey, TranslationKey> = {
  Dashboard: "nav.dashboard",
  Users: "nav.users",
  Roles: "nav.roles",
  "Audit Logs": "nav.auditLogs",
  "Create Dummy Mail": "nav.createDummyMail",
  Inbox: "nav.inbox",
  Interactions: "nav.interactions",
  Tickets: "nav.tickets",
  "Ticket Audit Log": "nav.ticketAuditLog",
  Profile: "nav.profile",
  Settings: "nav.settings",
};

// Staff/Team Lead/Manager — the actual agent roles — land on the
// embedded Ticket Management workspace at /dashboard instead of RBAC's
// own admin dashboard — see app/(dashboard)/dashboard/[[...slug]]/
// page.tsx and src/ticket-workspace/. Their sidebar shows the ticket
// workspace modules (matching Ticketing's own nav) alongside RBAC's
// own Users/Roles admin pages (same visibility as before the workspace
// was embedded — Users: Manager/Team Lead, Roles: Manager) plus
// Profile/Settings. "Ticket Audit Log" is the populated audit trail
// for ticket activity, linked for every agent role.
//
// Super Admin and Viewer both keep the original, unmodified RBAC
// dashboard/nav instead — Viewer as the client-facing role that was
// never an agent, Super Admin per an explicit later decision to keep
// that role's whole interface RBAC-only (Users/Roles/Dashboard/Profile/
// Settings), with no ticket-workspace nav items at all.
const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  [ROLE_NAMES.SUPER_ADMIN]: ["Dashboard", "Users", "Roles", "Profile", "Settings"],
  [ROLE_NAMES.MANAGER]: ["Dashboard", "Users", "Roles", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
  [ROLE_NAMES.TEAM_LEAD]: ["Dashboard", "Users", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
  [ROLE_NAMES.STAFF]: ["Dashboard", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
  [ROLE_NAMES.VIEWER]: ["Dashboard", "Profile", "Settings"],
};

const DEFAULT_NAV_ITEMS: NavItemKey[] = ["Dashboard", "Profile", "Settings"];

export function getVisibleNavItems(role: string | undefined): NavItemKey[] {
  if (!role) return [];
  return NAV_ITEMS_BY_ROLE[role] ?? DEFAULT_NAV_ITEMS;
}

export function canSeeNavItem(role: string | undefined, item: NavItemKey): boolean {
  return getVisibleNavItems(role).includes(item);
}

// Mirrors ticketing-service/backend/app/services/access_control.py's
// SUPERVISOR_ROLE_NAMES exactly — Team Lead/Manager/Super Admin see
// every ticket regardless of assignment, Staff sees only tickets
// assigned to them (or unassigned). The backend is what actually
// enforces this (GET /tickets scopes its own query by the caller's
// JWT), but the ticket workspace pages read this to describe the
// scope accurately rather than always claiming "assigned to you."
export const SUPERVISOR_ROLE_NAMES: readonly string[] = [
  ROLE_NAMES.TEAM_LEAD,
  ROLE_NAMES.MANAGER,
  ROLE_NAMES.SUPER_ADMIN,
];

export function isSupervisorRole(role: string | undefined): boolean {
  return !!role && SUPERVISOR_ROLE_NAMES.includes(role);
}

// Roles that a given logged-in role is permitted to assign when creating a
// new user. `undefined` means no restriction (all roles are selectable).
const CREATABLE_ROLES_BY_ROLE: Record<string, string[] | undefined> = {
  [ROLE_NAMES.SUPER_ADMIN]: undefined,
  [ROLE_NAMES.MANAGER]: [ROLE_NAMES.TEAM_LEAD, ROLE_NAMES.STAFF],
};

/**
 * Returns the role names the given role is allowed to assign on the Create
 * User form, or `null` when unrestricted. Roles with no entry here (Team
 * Lead, Staff, Viewer) cannot create users at all — gated separately by the
 * `user:create` permission.
 */
export function getCreatableRoleNames(role: string | undefined): string[] | null {
  if (!role || !(role in CREATABLE_ROLES_BY_ROLE)) return [];
  return CREATABLE_ROLES_BY_ROLE[role] ?? null;
}
