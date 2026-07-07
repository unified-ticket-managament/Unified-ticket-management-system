"use client";

import dynamic from "next/dynamic";
import { SiteLeadDashboard } from "@/components/dashboard/site-lead-dashboard";
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
// never an agent) and Super Admin (the RBAC-focused administrator role)
// keep the original RBAC dashboard; Site Lead gets its own dedicated
// dashboard (org oversight/permission governance is its day-to-day
// work, not ticket handling — see the RBAC redesign doc's "Primary vs.
// full" distinction); Staff/Team Lead/Account Manager — the actual
// agent roles — get the ticket workspace as their landing experience
// instead. None of Super Admin/Site Lead/Viewer's NAV_ITEMS_BY_ROLE
// entries (role-access.ts) include ticket-workspace nav items, so
// there's no in-app path into /dashboard/tickets etc. for those roles
// even though this same page technically serves that URL too.
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);

  if (role === ROLE_NAMES.SITE_LEAD) {
    return <SiteLeadDashboard />;
  }

  if (role === ROLE_NAMES.VIEWER || role === ROLE_NAMES.SUPER_ADMIN) {
    return <ViewerDashboard />;
  }

  return <TicketWorkspaceApp />;
}
