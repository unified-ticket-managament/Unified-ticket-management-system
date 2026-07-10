"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { AccountManagerDashboard } from "@/components/dashboard/account-manager-dashboard";
import { StaffDashboard } from "@/components/dashboard/staff-dashboard";
import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
import { TeamLeadDashboard } from "@/components/dashboard/team-lead-dashboard";
import { ViewerDashboard } from "@/components/dashboard/viewer-dashboard";
import { ROLE_NAMES } from "@/lib/role-access";
import { useAuthStore } from "@/store/auth-store";

// react-router-dom's <BrowserRouter> reads `window.location`/history at
// render time, which crashes Next's server-side render pass even inside
// a "use client" component (Next still renders client components on the
// server once, for the initial HTML). `ssr: false` skips that pass for
// this subtree and mounts it purely on the client instead.
const TicketWorkspaceApp = dynamic(
  () => import("@tw/TicketWorkspaceApp").then((mod) => mod.TicketWorkspaceApp),
  { ssr: false }
);

// Optional catch-all so every /dashboard/* path (the embedded ticket
// workspace's own routes — /dashboard/tickets, /dashboard/inbox, etc.)
// resolves to this one Next.js page. Viewer (the client-facing role,
// never an agent) keeps the original RBAC dashboard.
//
// Super Admin and Site Lead land on RBAC's own SuperAdminDashboard only
// for the bare /dashboard root (its Users/Roles/overview KPIs have no
// ticket-workspace equivalent) — any deeper slug (/dashboard/inbox,
// /dashboard/tickets, /dashboard/tickets/:id, /dashboard/interactions,
// /dashboard/audit-logs, /dashboard/create-mail) mounts the exact same
// real TicketWorkspaceApp Staff/Team Lead/Account Manager already use,
// with real backend data — see role-access.ts's NAV_ITEMS_BY_ROLE for
// why this replaced the old RBAC-native "All Tickets"/"My Tickets"
// pages (those were bound to static mock data with no live backend).
// Mounting the FULL app (not an isolated single page) is safe here:
// every route inside TicketWorkspaceApp's own <Routes> is something
// these two roles are now meant to reach anyway (CreateMailPage still
// self-gates to Site Lead only, backed by the real POST /emails/dummy
// 403 for anyone else), so there's no in-app link that would leak them
// somewhere they shouldn't be.
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);
  const params = useParams<{ slug?: string[] }>();
  const slug = params?.slug ?? [];

  if ((role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.SITE_LEAD) && slug.length > 0) {
    return <TicketWorkspaceApp />;
  }

  if (role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.SITE_LEAD) {
    return <SuperAdminDashboard />;
  }

  if (role === ROLE_NAMES.VIEWER) {
    return <ViewerDashboard />;
  }

  // Account Manager/Team Lead/Staff land on the same dashboard layout
  // Super Admin uses (per spec) for the bare /dashboard root, scoped
  // to their own data — any deeper slug still mounts the real
  // TicketWorkspaceApp exactly as before.
  if (role === ROLE_NAMES.ACCOUNT_MANAGER && slug.length === 0) {
    return <AccountManagerDashboard />;
  }

  if (role === ROLE_NAMES.TEAM_LEAD && slug.length === 0) {
    return <TeamLeadDashboard />;
  }

  if (role === ROLE_NAMES.STAFF && slug.length === 0) {
    return <StaffDashboard />;
  }

  return <TicketWorkspaceApp />;
}
