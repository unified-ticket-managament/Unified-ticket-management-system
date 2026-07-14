"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
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

function slugLengthFromPathname(pathname: string) {
  return pathname.replace(/^\/dashboard\/?/, "").split("/").filter(Boolean).length;
}

// Mounted here, one level above the `[[...slug]]` catch-all page, so it
// persists across every ticket-workspace-internal navigation (Mail,
// Tickets, Interactions, Audit Logs, Create Mail, a ticket's own detail
// page) instead of being torn down and recreated on each one.
//
// Next.js only preserves component state across a navigation for
// layouts, never for pages — even an optional catch-all page.tsx
// resolving the same file for every /dashboard/* slug still remounts on
// every slug change. Mounting TicketWorkspaceApp from that page meant
// WorkflowContext's "once per session" agents/clients/categories fetch,
// and every page hook's own "already loaded" cache (useMailInbox,
// TicketsListPage, ...), silently reran from scratch on every sidebar
// click between ticket-workspace pages. See the root-level performance
// audit for the measured request-count before/after.
export default function DashboardLayoutSegment({
  children,
}: {
  children: React.ReactNode;
}) {
  const role = useAuthStore((state) => state.user?.role);
  const pathname = usePathname();
  const slugLength = slugLengthFromPathname(pathname);

  // Mirrors the role/slug branching the catch-all page used to do itself
  // (see that file) — Viewer never sees the workspace; Super
  // Admin/Site Lead/Account Manager/Team Lead/Staff see it for any slug
  // deeper than the bare /dashboard root, where they instead get their
  // own role-specific dashboard (rendered by `children`, i.e. page.tsx).
  const showWorkspace =
    role === ROLE_NAMES.VIEWER
      ? false
      : role === ROLE_NAMES.SUPER_ADMIN ||
          role === ROLE_NAMES.SITE_LEAD ||
          role === ROLE_NAMES.ACCOUNT_MANAGER ||
          role === ROLE_NAMES.TEAM_LEAD ||
          role === ROLE_NAMES.STAFF
        ? slugLength > 0
        : true;

  if (!showWorkspace) {
    return <>{children}</>;
  }

  return <TicketWorkspaceApp />;
}
