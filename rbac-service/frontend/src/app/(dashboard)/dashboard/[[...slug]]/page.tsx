"use client";

import dynamic from "next/dynamic";
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
// keep the original RBAC dashboard; Staff/Team Lead/Manager — the actual
// agent roles — get the ticket workspace as their landing experience
// instead. Super Admin's own NAV_ITEMS_BY_ROLE entry (role-access.ts)
// has no ticket-workspace nav items, so there's no in-app path into
// /dashboard/tickets etc. for that role even though this same page
// technically serves that URL too.
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);

  if (role === ROLE_NAMES.VIEWER || role === ROLE_NAMES.SUPER_ADMIN) {
    return <ViewerDashboard />;
  }

  return <TicketWorkspaceApp />;
}
