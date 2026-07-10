"use client";

import { useMemo } from "react";

import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
import { getTicketsForStaff } from "@/lib/mock-tickets";
import { useAuthStore } from "@/store/auth-store";

// Identical layout/components to Super Admin's dashboard — only the
// ticket data feeding it differs, scoped to this Staff member's own
// assigned tickets (see getTicketsForStaff for how that scoping works
// given the mock dataset has no real assignee-id link).
export function StaffDashboard() {
  const currentUser = useAuthStore((state) => state.user);

  const tickets = useMemo(
    () => (currentUser ? getTicketsForStaff(currentUser.user_id) : []),
    [currentUser]
  );

  return (
    <SuperAdminDashboard
      tickets={tickets}
      description="Your assigned tickets at a glance."
    />
  );
}
