"use client";

import { useMemo } from "react";

import { SuperAdminDashboard } from "@/components/dashboard/super-admin-dashboard";
import { getTicketsForTeamLead } from "@/lib/mock-tickets";
import { useAuthStore } from "@/store/auth-store";

// Identical layout/components to Super Admin's dashboard — only the
// ticket data feeding it differs, scoped to this Team Lead's team
// (see getTicketsForTeamLead for how that scoping works given the
// mock dataset has no real team-ownership link).
export function TeamLeadDashboard() {
  const currentUser = useAuthStore((state) => state.user);

  const tickets = useMemo(
    () => (currentUser ? getTicketsForTeamLead(currentUser.user_id) : []),
    [currentUser]
  );

  return (
    <SuperAdminDashboard
      tickets={tickets}
      description="Ticket operations overview for your team."
    />
  );
}
