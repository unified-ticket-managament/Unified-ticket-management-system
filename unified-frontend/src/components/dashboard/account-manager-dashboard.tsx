"use client";

import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";

// Identical layout/components to Super Admin's dashboard — SuperAdminDashboard
// now fetches its own real data (getDashboardStats/listTickets/audit logs),
// and those endpoints already scope to this Account Manager's own clients
// server-side, so no client-side ticket subset needs to be passed in here.
export function AccountManagerDashboard() {
  return <SuperAdminDashboard description="Ticket operations overview for your clients." />;
}
