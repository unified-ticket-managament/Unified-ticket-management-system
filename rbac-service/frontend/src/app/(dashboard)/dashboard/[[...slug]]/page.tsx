"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
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

// Site Lead's one, deliberately narrow exception to "Site Lead never
// reaches the ticket workspace" (see the role check below) — the
// dummy-mail simulator, rendered on its own rather than via the full
// TicketWorkspaceApp. See DummyMailOnlyApp's own docstring for why
// that isolation matters (mounting the full app's <BrowserRouter>
// would let an in-app <Link> navigate Site Lead into every other
// ticket-workspace route without this page's role check running
// again).
const DummyMailOnlyApp = dynamic(
  () => import("@tw/DummyMailOnlyApp").then((mod) => mod.DummyMailOnlyApp),
  { ssr: false }
);

// Optional catch-all so every /dashboard/* path (the embedded ticket
// workspace's own routes — /dashboard/tickets, /dashboard/inbox, etc.)
// resolves to this one Next.js page. Viewer (the client-facing role,
// never an agent) keeps the original RBAC dashboard; Super Admin and
// Site Lead share the exact same ticket-operations dashboard
// (SuperAdminDashboard, mock-data backed — see lib/mock-tickets.ts) per
// an explicit product decision that Site Lead's interface should look
// identical to Super Admin's, differing only in which actions are
// available (see canDeleteRecords/canManageRoles in role-access.ts);
// Staff/Team Lead/Manager — the actual agent roles — get the ticket
// workspace as their landing experience instead. Both Super Admin's and
// Site Lead's NAV_ITEMS_BY_ROLE entries have no ticket-workspace nav
// items, so there's no in-app path into /dashboard/tickets etc. for
// either role even though this same page technically serves that URL
// too.
export default function DashboardCatchAllPage() {
  const role = useAuthStore((state) => state.user?.role);
  const params = useParams<{ slug?: string[] }>();
  const slug = params?.slug ?? [];

  if (role === ROLE_NAMES.SITE_LEAD && slug.length === 1 && slug[0] === "create-mail") {
    return <DummyMailOnlyApp />;
  }

  if (role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.SITE_LEAD) {
    return <SuperAdminDashboard />;
  }

  if (role === ROLE_NAMES.VIEWER) {
    return <ViewerDashboard />;
  }

  return <TicketWorkspaceApp />;
}
