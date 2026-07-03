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

// Mounts the (unmodified) Ticketing frontend's page tree inside RBAC's
// own Next.js app, under the `/dashboard` route. RBAC's own
// DashboardLayout (Sidebar/TopNavbar/AuthGuard) already wraps this one
// level up — this only owns the react-router basename below it, so
// none of the copied pages' internal navigation (useNavigate, <Link
// to="...">, useParams) needed to change.
export function TicketWorkspaceApp() {
  return (
    <div className="tm-scope">
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
