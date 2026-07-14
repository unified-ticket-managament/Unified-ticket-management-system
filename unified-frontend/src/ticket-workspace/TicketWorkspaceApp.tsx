"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { ToastProvider } from "@tw/context/ToastContext";
import { WorkflowProvider } from "@tw/context/WorkflowContext";
import { ToastViewport } from "@tw/components/common/ToastViewport";
import { Dashboard } from "@tw/pages/Dashboard";
import { CreateMailPage } from "@tw/pages/CreateMailPage";
import { InboxPage } from "@tw/pages/InboxPage";
import { InteractionsPage } from "@tw/pages/InteractionsPage";
import { FullInteractionPage } from "@tw/pages/FullInteractionPage";
import { TicketsListPage } from "@tw/pages/TicketsListPage";
import { TicketDetailPage } from "@tw/pages/TicketDetailPage";
import { TicketInteractionPage } from "@tw/pages/TicketInteractionPage";
import { AuditLogPage } from "@tw/pages/AuditLogPage";

// react-router's BrowserRouter only learns about a URL change through
// its own push()/replace() calls or a browser `popstate` event — it
// does not monkey-patch `window.history.pushState`, so a navigation
// triggered by something else entirely (the shell sidebar's `next/link`,
// handled by Next's own client-side router) changes the address bar
// without react-router ever finding out, leaving its <Routes> matched
// against a stale location. This was invisible before: the whole
// TicketWorkspaceApp (BrowserRouter included) used to remount on every
// such navigation, so a fresh BrowserRouter always read the correct
// window.location at mount time. Now that it's intentionally kept
// mounted (see dashboard/layout.tsx) to fix the request-duplication
// bug, this component bridges the gap: whenever Next's own pathname
// changes, it forces react-router's location to catch up. Navigation
// react-router itself initiates (a page's own useNavigate()/<Link to=...>,
// e.g. opening a ticket row) is unaffected — those already update
// react-router's location directly and are not routed through here.
function RouterSync() {
  const nextPathname = usePathname();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const relative = nextPathname.replace(/^\/dashboard/, "") || "/";
    if (relative !== location.pathname) {
      navigate(relative, { replace: true });
    }
    // Deliberately only re-sync when Next's own pathname changes, not
    // on every location change — re-running this on react-router's own
    // location updates too would fight its own in-app navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nextPathname]);

  return null;
}

// Mounts the (unmodified) Ticketing frontend's page tree inside RBAC's
// own Next.js app, under the `/dashboard` route. RBAC's own
// DashboardLayout (Sidebar/TopNavbar/AuthGuard) already wraps this one
// level up — this only owns the react-router basename below it, so
// none of the copied pages' internal navigation (useNavigate, <Link
// to="...">, useParams) needed to change.
//
// `.tm-scope` (globals.css) remaps Ticketing's own multi-hue accent
// palette (warning/danger/success/info/teal, plus its blue "accent")
// onto RBAC's own monochrome palette, so this subtree reads as the
// same product as RBAC's Profile/Settings pages for every role.
export function TicketWorkspaceApp() {
  return (
    <div className="tm-scope">
      <ToastProvider>
        <WorkflowProvider>
          <BrowserRouter basename="/dashboard">
            <RouterSync />
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/create-mail" element={<CreateMailPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/interactions" element={<InteractionsPage />} />
              <Route path="/interactions/:interactionId" element={<FullInteractionPage />} />
              <Route path="/tickets" element={<TicketsListPage />} />
              <Route path="/tickets/:ticketId" element={<TicketDetailPage />} />
              <Route path="/tickets/:ticketId/interactions" element={<TicketInteractionPage />} />
              <Route path="/audit-logs" element={<AuditLogPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          <ToastViewport />
        </WorkflowProvider>
      </ToastProvider>
    </div>
  );
}
