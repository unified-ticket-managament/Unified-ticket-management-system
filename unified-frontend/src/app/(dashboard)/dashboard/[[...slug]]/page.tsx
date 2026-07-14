"use client";

import { AccountManagerDashboard } from "@/components/dashboard/account-manager-dashboard";
import { StaffDashboard } from "@/components/dashboard/staff-dashboard";
import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
import { TeamLeadDashboard } from "@/components/dashboard/team-lead-dashboard";
import { ViewerDashboard } from "@/components/dashboard/viewer-dashboard";
import { ROLE_NAMES } from "@/lib/role-access";
import { useAuthStore } from "@/store/auth-store";

// Only ever rendered as `children` by the parent `dashboard/layout.tsx`,
// and only for the "root dashboard" case: the bare /dashboard root for
// Super Admin/Site Lead/Account Manager/Team Lead/Staff, or Viewer at
// any depth. Every deeper ticket-workspace route (/dashboard/inbox,
// /dashboard/tickets, /dashboard/tickets/:id, ...) is instead handled by
// that layout mounting TicketWorkspaceApp directly and never rendering
// this page at all — see that file for the full routing/persistence
// rationale (this used to also decide when to render TicketWorkspaceApp
// itself, which meant the workspace remounted on every slug change).
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);

  if (role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.SITE_LEAD) {
    return <SuperAdminDashboard />;
  }

  if (role === ROLE_NAMES.VIEWER) {
    return <ViewerDashboard />;
  }

  if (role === ROLE_NAMES.ACCOUNT_MANAGER) {
    return <AccountManagerDashboard />;
  }

  if (role === ROLE_NAMES.TEAM_LEAD) {
    return <TeamLeadDashboard />;
  }

  if (role === ROLE_NAMES.STAFF) {
    return <StaffDashboard />;
  }

  return null;
}
