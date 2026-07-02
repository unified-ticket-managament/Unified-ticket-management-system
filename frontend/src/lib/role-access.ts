export type NavItemKey =
  | "Dashboard"
  | "Users"
  | "Roles"
  | "Permissions"
  | "Audit Logs"
  | "Profile"
  | "Settings";

const NAV_ITEMS_BY_ROLE: Record<string, NavItemKey[]> = {
  "Super Admin": [
    "Dashboard",
    "Users",
    "Roles",
    "Permissions",
    "Audit Logs",
    "Profile",
    "Settings",
  ],
  Manager: ["Dashboard", "Users", "Roles", "Profile", "Settings"],
  "Team Lead": ["Dashboard", "Users", "Profile", "Settings"],
  Staff: ["Dashboard", "Profile", "Settings"],
  Viewer: ["Dashboard", "Profile", "Settings"],
};

const DEFAULT_NAV_ITEMS: NavItemKey[] = ["Dashboard", "Profile", "Settings"];

export function getVisibleNavItems(role: string | undefined): NavItemKey[] {
  if (!role) return [];
  return NAV_ITEMS_BY_ROLE[role] ?? DEFAULT_NAV_ITEMS;
}

export function canSeeNavItem(role: string | undefined, item: NavItemKey): boolean {
  return getVisibleNavItems(role).includes(item);
}
