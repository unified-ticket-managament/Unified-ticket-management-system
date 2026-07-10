"use client";

import { useMemo } from "react";

import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
import { getTicketsForAccountManager } from "@/lib/mock-tickets";
import { useAuthStore } from "@/store/auth-store";

// Identical layout/components to Super Admin's dashboard (per spec:
// "reuse existing components", "layout should remain identical") —
// only the ticket data feeding it differs, scoped to this Account
// Manager (see getTicketsForAccountManager for how that scoping
// works given the mock dataset has no real client-ownership link).
export function AccountManagerDashboard() {
  const currentUser = useAuthStore((state) => state.user);

  const tickets = useMemo(
    () => (currentUser ? getTicketsForAccountManager(currentUser.user_id) : []),
    [currentUser]
  );

  return (
    <SuperAdminDashboard
      tickets={tickets}
      description="Ticket operations overview for your clients."
    />
  );
}
