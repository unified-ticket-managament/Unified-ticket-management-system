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
// never an agent) keeps the original RBAC dashboard; every other role
// (Staff, Team Lead, Manager, Super Admin) gets the ticket workspace as
// their landing experience instead.
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);

  if (role === ROLE_NAMES.VIEWER) {
    return <ViewerDashboard />;
  }

  return <TicketWorkspaceApp />;
}
