import type { ReactNode } from "react";
import { PageHeader } from "@/components/layout/dashboard-shell";

interface AppLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

// Drop-in replacement for the standalone Ticketing app's AppLayout —
// same props, so none of the copied pages need to change. RBAC's own
// DashboardLayout (rendered one level up, outside the embedded router)
// already provides the Sidebar/Topbar chrome; this only renders the
// per-page title bar, reusing RBAC's own PageHeader component instead
// of duplicating one.
export function AppLayout({ title, description, children }: AppLayoutProps) {
  return (
    <div className="tm-scope">
      <PageHeader title={title} description={description} />
      {children}
    </div>
  );
}
