import { TranslationKey } from "@/lib/i18n/translations";

export const ROLE_NAMES = {
  SUPER_ADMIN: "Super Admin",
  SITE_LEAD: "Site Lead",
  ACCOUNT_MANAGER: "Account Manager",
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

// Staff/Team Lead/Account Manager — the actual agent roles — land on
// the embedded Ticket Management workspace at /dashboard instead of
// RBAC's own admin dashboard — see app/(dashboard)/dashboard/
// [[...slug]]/page.tsx and src/ticket-workspace/. Their sidebar shows
// the ticket workspace modules (matching Ticketing's own nav) alongside
// RBAC's own Users/Roles admin pages (same visibility as before the
// workspace was embedded — Users: Account Manager/Team Lead, Roles:
// Account Manager) plus Profile/Settings. "Ticket Audit Log" is the
// populated audit trail for ticket activity, linked for every agent role.
//
// Super Admin, Site Lead, and Viewer all keep the original, unmodified
// RBAC dashboard/nav instead of the ticket workspace — Viewer as the
// client-facing role that was never an agent; Super Admin per an
// explicit decision to keep that role's whole interface RBAC-only;
// Site Lead because its day-to-day work is org oversight and permission
// governance, not hands-on ticket work (see the "Primary vs. full"
// distinction in the RBAC redesign doc) — Site Lead still holds full
// ticket permissions, it just isn't routed to the ticket workspace UI,
// the same way Super Admin already wasn't.
//
// "Audit Logs" (the RBAC-level log, distinct from "Ticket Audit Log")
// is included for Super Admin and Site Lead, the two roles with the
// `audit:view` permission by default.
const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  [ROLE_NAMES.SUPER_ADMIN]: ["Dashboard", "Users", "Roles", "Audit Logs", "Profile", "Settings"],
  [ROLE_NAMES.SITE_LEAD]: ["Dashboard", "Users", "Roles", "Audit Logs", "Profile", "Settings"],
  [ROLE_NAMES.ACCOUNT_MANAGER]: ["Dashboard", "Users", "Roles", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Ticket Audit Log", "Profile", "Settings"],
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
// SUPERVISOR_ROLE_NAMES exactly — Team Lead/Account Manager/Site Lead/
// Super Admin see every ticket regardless of assignment, Staff sees
// only tickets assigned to them (or unassigned). The backend is what
// actually enforces this (GET /tickets scopes its own query by the
// caller's JWT), but the ticket workspace pages read this to describe
// the scope accurately rather than always claiming "assigned to you."
export const SUPERVISOR_ROLE_NAMES: readonly string[] = [
  ROLE_NAMES.TEAM_LEAD,
  ROLE_NAMES.ACCOUNT_MANAGER,
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.SUPER_ADMIN,
];

export function isSupervisorRole(role: string | undefined): boolean {
  return !!role && SUPERVISOR_ROLE_NAMES.includes(role);
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
