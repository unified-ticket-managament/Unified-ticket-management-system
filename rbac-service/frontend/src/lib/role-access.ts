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
  | "Ticket Workspace"
  | "Profile"
  | "Settings";

export const NAV_ITEM_TRANSLATION_KEY: Record<NavItemKey, TranslationKey> = {
  Dashboard: "nav.dashboard",
  Users: "nav.users",
  Roles: "nav.roles",
  "Audit Logs": "nav.auditLogs",
  "Ticket Workspace": "nav.ticketWorkspace",
  Profile: "nav.profile",
  Settings: "nav.settings",
};

// Permission management now lives inside the User Details drawer (Users
// page) instead of a standalone page/nav item. Audit Logs is no longer
// linked from any role's sidebar per the latest spec, but the page itself
// still exists and is reachable from the Dashboard's quick actions.
//
// "Ticket Workspace" links out to the separate Ticketing frontend
// (different app/origin — see components/layout/sidebar.tsx) for every
// role except Viewer, matching Ticketing's own AGENT_ROLE_NAMES (every
// role except Viewer can log into and act on tickets there).
const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  [ROLE_NAMES.SUPER_ADMIN]: ["Dashboard", "Users", "Roles", "Ticket Workspace", "Profile", "Settings"],
  [ROLE_NAMES.MANAGER]: ["Dashboard", "Users", "Roles", "Ticket Workspace", "Profile", "Settings"],
  [ROLE_NAMES.TEAM_LEAD]: ["Dashboard", "Users", "Ticket Workspace", "Profile", "Settings"],
  [ROLE_NAMES.STAFF]: ["Dashboard", "Ticket Workspace", "Profile", "Settings"],
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
