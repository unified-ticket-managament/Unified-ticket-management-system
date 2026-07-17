"use client";

import Link from "next/link";
import { CheckCircle2, Inbox, LayoutDashboard, ListTodo } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DashboardStats } from "@tw/api/ticket";

interface AccountSummaryCardProps {
  stats: DashboardStats | null;
  isLoading: boolean;
  slaCompliancePct: number | null;
}

// Reuses the exact same GET /tickets/dashboard-stats + SLA-overview data
// the Dashboard page already fetches (see useProfileData) — no new
// backend endpoint. Counts are visibility-scoped exactly like the
// Dashboard's own KPI cards (org-wide for Super Admin/Site Lead,
// own-clients/own-category for Account Manager/Team Lead/Staff).
export function AccountSummaryCard({ stats, isLoading, slaCompliancePct }: AccountSummaryCardProps) {
  const items = [
    { label: "Open Tickets", value: stats?.open, icon: Inbox },
    { label: "Assigned Tickets", value: stats?.assigned, icon: ListTodo },
    { label: "Resolved Tickets", value: stats?.resolved, icon: CheckCircle2 },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-base">Account Summary</CardTitle>
        <CardDescription>Across your current visibility scope.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {items.map((item) => (
          <div key={item.label} className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-sm text-muted-foreground">
              <item.icon className="h-4 w-4" />
              {item.label}
            </span>
            <span className="text-sm font-semibold">
              {isLoading || item.value === undefined ? "…" : item.value}
            </span>
          </div>
        ))}

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">SLA Compliance</span>
          <span className="text-sm font-semibold">
            {slaCompliancePct === null ? "—" : `${slaCompliancePct}%`}
          </span>
        </div>

        <Button variant="outline" className="w-full gap-2" asChild>
          <Link href="/dashboard">
            <LayoutDashboard className="h-4 w-4" />
            View My Dashboard
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
