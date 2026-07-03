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
  Profile: "nav.profile",
  Settings: "nav.settings",
};

// Every role except Viewer (the client-facing role, never an agent)
// now lands on the embedded Ticket Management workspace at /dashboard
// instead of RBAC's own admin dashboard — see
// app/(dashboard)/dashboard/[[...slug]]/page.tsx and
// src/ticket-workspace/. Their sidebar shows only the ticket workspace
// modules (matching Ticketing's own nav) plus Profile/Settings; Users/
// Roles/Audit Logs stay fully functional at their existing routes, just
// no longer linked from the primary sidebar for these roles. Viewer
// keeps the original RBAC dashboard and nav, unchanged.
const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  [ROLE_NAMES.SUPER_ADMIN]: ["Dashboard", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Profile", "Settings"],
  [ROLE_NAMES.MANAGER]: ["Dashboard", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Profile", "Settings"],
  [ROLE_NAMES.TEAM_LEAD]: ["Dashboard", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Profile", "Settings"],
  [ROLE_NAMES.STAFF]: ["Dashboard", "Create Dummy Mail", "Inbox", "Interactions", "Tickets", "Profile", "Settings"],
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
