"use client";

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "@tw/context/ToastContext";
import { WorkflowProvider } from "@tw/context/WorkflowContext";
import { ToastViewport } from "@tw/components/common/ToastViewport";
import { Dashboard } from "@tw/pages/Dashboard";
import { CreateMailPage } from "@tw/pages/CreateMailPage";
import { InboxPage } from "@tw/pages/InboxPage";
import { InteractionsPage } from "@tw/pages/InteractionsPage";
import { TicketsListPage } from "@tw/pages/TicketsListPage";
import { TicketDetailPage } from "@tw/pages/TicketDetailPage";
import { AuditLogPage } from "@tw/pages/AuditLogPage";
import { ROLE_NAMES } from "@/lib/role-access";
import { useAuthStore } from "@/store/auth-store";

// Mounts the (unmodified) Ticketing frontend's page tree inside RBAC's
// own Next.js app, under the `/dashboard` route. RBAC's own
// DashboardLayout (Sidebar/TopNavbar/AuthGuard) already wraps this one
// level up — this only owns the react-router basename below it, so
// none of the copied pages' internal navigation (useNavigate, <Link
// to="...">, useParams) needed to change.
export function TicketWorkspaceApp() {
  const role = useAuthStore((state) => state.user?.role);

  // Ticketing's own multi-hue accent palette (warning/danger/success/
  // info/teal, plus its blue "accent") made this subtree look like a
  // visibly different product next to RBAC's monochrome Profile/
  // Settings pages. `.tm-unified-theme` (globals.css) remaps those
  // tokens onto RBAC's own palette instead. Scoped to Staff only for
  // now, per request — Team Lead/Manager/Super Admin keep the
  // original ticket-workspace look unchanged.
  const useUnifiedTheme = role === ROLE_NAMES.STAFF;

  return (
    <div className={useUnifiedTheme ? "tm-scope tm-unified-theme" : "tm-scope"}>
      <ToastProvider>
        <WorkflowProvider>
          <BrowserRouter basename="/dashboard">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/create-mail" element={<CreateMailPage />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/interactions" element={<InteractionsPage />} />
              <Route path="/tickets" element={<TicketsListPage />} />
              <Route path="/tickets/:ticketId" element={<TicketDetailPage />} />
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
