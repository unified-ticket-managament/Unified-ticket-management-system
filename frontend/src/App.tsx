import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { WorkflowProvider } from "@/context/WorkflowContext";
import { ToastProvider } from "@/context/ToastContext";
import { Dashboard } from "@/pages/Dashboard";
import { CreateMailPage } from "@/pages/CreateMailPage";
import { InboxPage } from "@/pages/InboxPage";
import { InteractionsPage } from "@/pages/InteractionsPage";
import { TicketsListPage } from "@/pages/TicketsListPage";
import { TicketDetailPage } from "@/pages/TicketDetailPage";

export function App() {
  return (
    <ToastProvider>
      <WorkflowProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/create-mail" element={<CreateMailPage />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/interactions" element={<InteractionsPage />} />
            <Route path="/tickets" element={<TicketsListPage />} />
            <Route path="/tickets/:ticketId" element={<TicketDetailPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </WorkflowProvider>
    </ToastProvider>
  );
}
