import { TranslationKey } from "@/lib/i18n/translations";

export const ROLE_NAMES = {
  SUPER_ADMIN: "Super Admin",

  // No role is literally named "Manager" in this system — kept here
  // only because other admin-permission call sites still reference
  // it (dead until/unless that role is actually created). Account
  // Manager and Site Lead are the two real roles this system uses.
  MANAGER: "Manager",
  ACCOUNT_MANAGER: "Account Manager",
  SITE_LEAD: "Site Lead",

  TEAM_LEAD: "Team Lead",
  STAFF: "Staff",
  VIEWER: "Viewer",
} as const;

export type NavItemKey =
  | "Dashboard"
  | "All Tickets"
  | "My Tickets"
  | "Users"
  | "Roles"
  | "Audit Logs"
  | "Reports"
  | "Create Dummy Mail"
  | "Inbox"
  | "Interactions"
  | "Tickets"
  | "Ticket Audit Log"
  | "Profile"
  | "Settings";

export const NAV_ITEM_TRANSLATION_KEY: Record<NavItemKey, TranslationKey> = {
  Dashboard: "nav.dashboard",
  "All Tickets": "nav.allTickets",
  "My Tickets": "nav.myTickets",
  Users: "nav.users",
  Roles: "nav.roles",
  "Audit Logs": "nav.auditLogs",
  Reports: "nav.reports",
  "Create Dummy Mail": "nav.createDummyMail",
  Inbox: "nav.inbox",
  Interactions: "nav.interactions",
  Tickets: "nav.tickets",
  "Ticket Audit Log": "nav.ticketAuditLog",
  Profile: "nav.profile",
  Settings: "nav.settings",
};



// Staff/Team Lead/Account Manager — the hands-on agent roles — land on
// the embedded Ticket Management workspace at /dashboard instead of
// RBAC's own admin dashboard — see
// app/(dashboard)/dashboard/[[...slug]]/page.tsx and
// src/ticket-workspace/. Their sidebar shows the ticket workspace
// modules (matching Ticketing's own nav) plus Profile/Settings.
// "Ticket Audit Log" is the populated audit trail for ticket
// activity, linked for every agent role.
//
// Site Lead's sidebar is intentionally IDENTICAL to Super Admin's (per
// an explicit product decision — see canDeleteRecords/canManageRoles
// below for how the two roles then diverge on actions, not navigation).
// Account Manager/Team Lead/Staff still don't manage users or roles.
//
// Super Admin and Site Lead land on RBAC's own SuperAdminDashboard for
// the bare /dashboard root (Users/Roles/overview stuff has no ticket-
// workspace equivalent), but — unlike an earlier version of this file —
// they ALSO get the real ticket-workspace modules (Inbox/Interactions/
// Tickets/Ticket Audit Log) instead of the RBAC-native "All Tickets"/
// "My Tickets" pages, which were bound to static mock data
// (lib/mock-tickets.ts) with no live backend behind them. The ticket
// workspace's own Tickets page already has "Open Pool"/"My Tickets"/
// "All" tabs built in, so nothing extra was needed to cover both.
// Viewer keeps the original, unmodified RBAC dashboard/nav — the
// client-facing role that was never an agent.
//
// "Audit Logs" (the RBAC-level log, distinct from "Ticket Audit Log")
// is included for Super Admin and Site Lead, the two roles with the
// `audit:view` permission by default.
const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  [ROLE_NAMES.SUPER_ADMIN]: [
    "Dashboard",
    "Users",
    "Roles",
    "Audit Logs",
    "Reports",
    "Inbox",
    "Interactions",
    "Tickets",
    "Ticket Audit Log",
    "Settings",
  ],
  [ROLE_NAMES.SITE_LEAD]: [
    "Dashboard",
    "Users",
    "Roles",
    "Audit Logs",
    "Reports",
    "Create Dummy Mail",
    "Inbox",
    "Interactions",
    "Tickets",
    "Ticket Audit Log",
    "Settings",
  ],
  [ROLE_NAMES.ACCOUNT_MANAGER]: ["Dashboard", "Users", "Roles", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
  [ROLE_NAMES.TEAM_LEAD]: ["Dashboard", "Users", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
  [ROLE_NAMES.STAFF]: ["Dashboard", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
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
// SUPERVISOR_ROLE_NAMES exactly — Super Admin/Site Lead see every
// ticket regardless of client ownership; everyone else is scoped
// (Account Manager to their own clients; Team Lead/Staff unrestricted
// until category-based routing is defined — see that file's comment).
// The backend is what actually enforces this (GET /tickets scopes its
// own query by the caller's JWT), but the ticket workspace pages read
// this to describe the scope accurately rather than always claiming
// "assigned to you."
export const SUPERVISOR_ROLE_NAMES: readonly string[] = [
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.SUPER_ADMIN,
];

export function isSupervisorRole(role: string | undefined): boolean {
  return !!role && SUPERVISOR_ROLE_NAMES.includes(role);
}

// Site Lead reuses every Super Admin page/component as-is (same sidebar,
// same tables, same dialogs — see NAV_ITEMS_BY_ROLE above) but is denied
// a handful of destructive/structural actions on top of that shared UI.
// This is deliberately a frontend-only gate, independent of the ticket:*/
// user:*/role:* permission strings PermissionGuard checks: the backend
// currently grants Site Lead nearly every permission (rank 4, "all
// permissions except ticket:system_config/audit:export" — see
// CLAUDE.md), which does not line up with this narrower product
// decision. Call sites should combine this with the existing
// PermissionGuard, not replace it, so tightening the backend grants
// later only makes the UI more restrictive, never less.
export function canDeleteRecords(role: string | undefined): boolean {
  return role === ROLE_NAMES.SUPER_ADMIN;
}

// Role creation/editing/deletion ("modifying role structure") stays
// Super Admin-only; Site Lead's Roles page is view-only (role info,
// permissions, assigned users).
export function canManageRoles(role: string | undefined): boolean {
  return role === ROLE_NAMES.SUPER_ADMIN;
}

// Roles that a given logged-in role is permitted to assign when creating a
// new user. `undefined` means no restriction (all roles are selectable).
const CREATABLE_ROLES_BY_ROLE: Record<string, string[] | undefined> = {
  [ROLE_NAMES.SUPER_ADMIN]: undefined,
  [ROLE_NAMES.SITE_LEAD]: [ROLE_NAMES.ACCOUNT_MANAGER, ROLE_NAMES.TEAM_LEAD, ROLE_NAMES.STAFF],
  [ROLE_NAMES.ACCOUNT_MANAGER]: [ROLE_NAMES.TEAM_LEAD, ROLE_NAMES.STAFF],
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
