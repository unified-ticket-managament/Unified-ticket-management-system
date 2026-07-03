import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { WorkflowProvider } from "@/context/WorkflowContext";
import { ToastProvider } from "@/context/ToastContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthGuard } from "@/components/layout/AuthGuard";
import { LoginPage } from "@/pages/LoginPage";
import { Dashboard } from "@/pages/Dashboard";
import { CreateMailPage } from "@/pages/CreateMailPage";
import { InboxPage } from "@/pages/InboxPage";
import { InteractionsPage } from "@/pages/InteractionsPage";
import { TicketsListPage } from "@/pages/TicketsListPage";
import { TicketDetailPage } from "@/pages/TicketDetailPage";
import { AuditLogPage } from "@/pages/AuditLogPage";

export function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                path="*"
                element={
                  <AuthGuard>
                    <WorkflowProvider>
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
                    </WorkflowProvider>
                  </AuthGuard>
                }
              />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  );
}
