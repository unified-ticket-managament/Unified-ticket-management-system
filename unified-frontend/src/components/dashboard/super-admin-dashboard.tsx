"use client";

import Link from "next/link";
import {
  Archive,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Loader2,
  Ticket,
} from "lucide-react";
import { useMemo } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { ModernBarListCard } from "@/components/dashboard/ModernBarListCard";
import { ModernStatCard } from "@/components/dashboard/ModernStatCard";
import { SlaOverviewSection } from "@/components/dashboard/SlaOverviewSection";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getCountsByPriority,
  getCountsByStatus,
  getDashboardKpis,
  MOCK_RECENT_ACTIVITIES,
  MOCK_TICKETS,
  STATUS_COLOR,
} from "@/lib/mock-tickets";
import { formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import type { MockTicket } from "@/lib/mock-tickets";

// Chart-only semantic color remap for the reference design (blue/orange/
// green/purple/red/gray per category) — deliberately local to this page,
// not written back into lib/mock-tickets.ts's PRIORITY_COLOR/STATUS_COLOR
// (those still drive the unrelated Badge `tone` used on ticket pages, and
// changing them there would also repaint viewer-dashboard.tsx's charts,
// which reuses the same exported constants and is out of scope here).
const PRIORITY_CHART_COLOR: Record<string, string> = {
  Low: "bg-blue-500",
  Medium: "bg-orange-500",
  High: "bg-red-500",
  Critical: "bg-purple-500",
};
const STATUS_CHART_COLOR: Record<string, string> = {
  Open: "bg-blue-500",
  "In Progress": "bg-orange-500",
  Resolved: "bg-green-500",
  Closed: "bg-gray-400",
};

interface SuperAdminDashboardProps {
  // Defaults to the full mock dataset (Super Admin's own view).
  // Account Manager/Team Lead/Staff dashboards reuse this exact same
  // component/layout, passing in their own role-scoped subset (see
  // getTicketsForAccountManager/getTicketsForTeamLead/getTicketsForStaff
  // in lib/mock-tickets.ts) — every KPI/chart/list below is already a
  // pure derivation of `tickets`, so no other change was needed to
  // make this reusable per role.
  tickets?: MockTicket[];
  description?: string;
}

// Super Admin's ticket-operations dashboard — replaces the generic
// ViewerDashboard for this role only (see dashboard/[[...slug]]/page.tsx).
// KPIs/charts run on the mock dataset in lib/mock-tickets.ts since the
// backend has no aggregation endpoints for these yet; swap the source
// here for a real query once it does — the shape (six KPIs + two
// breakdowns + two recent lists) is meant to stay stable across that swap.
export function SuperAdminDashboard({ tickets = MOCK_TICKETS, description }: SuperAdminDashboardProps) {
  const currentUser = useAuthStore((state) => state.user);

  const kpis = useMemo(() => getDashboardKpis(tickets), [tickets]);
  const priorityBreakdown = useMemo(
    () => getCountsByPriority(tickets).map((d) => ({ ...d, color: PRIORITY_CHART_COLOR[d.label] ?? d.color })),
    [tickets]
  );
  const statusBreakdown = useMemo(
    () => getCountsByStatus(tickets).map((d) => ({ ...d, color: STATUS_CHART_COLOR[d.label] ?? d.color })),
    [tickets]
  );

  const recentAssigned = useMemo(
    () =>
      [...tickets]
        .sort((a, b) => new Date(b.updatedDate).getTime() - new Date(a.updatedDate).getTime())
        .slice(0, 5),
    [tickets]
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${currentUser?.name ?? "there"}`}
        description={description ?? "Ticket operations overview across the organization."}
      />

      {/* Top KPI row — deliberately only 4 tiles now (Open/Resolved
          Today/In Progress/Closed). SLA Breaches and Escalated Tickets
          were removed from this row only — both are still fully live
          just below, as the real (non-mock) "Breached"/"Escalated"
          tiles in SlaOverviewSection, so no functionality was dropped. */}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <ModernStatCard title="Open Tickets" value={kpis.open} subtitle="Awaiting first response" icon={Ticket} />
        <ModernStatCard
          title="Resolved Today"
          value={kpis.resolvedToday}
          subtitle="Closed within SLA"
          icon={CheckCircle2}
          tone="success"
        />
        <ModernStatCard title="In Progress" value={kpis.inProgress} subtitle="Actively being worked" icon={Clock} tone="warning" />
        <ModernStatCard title="Closed" value={kpis.closed} subtitle="All-time closed" icon={Archive} />
      </div>

      <SlaOverviewSection />

      <div className="grid gap-5 lg:grid-cols-2">
        <ModernBarListCard
          title="Tickets by Priority"
          description="Current open workload by priority level"
          data={priorityBreakdown}
          legend={Object.entries(PRIORITY_CHART_COLOR).map(([label, bar]) => ({ label, dotClassName: bar }))}
        />

        <ModernBarListCard
          title="Tickets by Status"
          description="Distribution across the ticket lifecycle"
          data={statusBreakdown}
          legend={Object.entries(STATUS_CHART_COLOR).map(([label, bar]) => ({ label, dotClassName: bar }))}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="rounded-md border-border shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent Activity</CardTitle>
              <CardDescription>Latest ticket actions across the team</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-1">
            {MOCK_RECENT_ACTIVITIES.map((activity) => (
              <div key={activity.id} className="flex items-start gap-3 rounded-md px-2.5 py-3 transition-colors hover:bg-muted/50">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                  <Loader2 className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    <span className="font-medium">{activity.actor}</span>{" "}
                    <span className="text-muted-foreground">{activity.action}</span>{" "}
                    <span className="font-medium">{activity.ticketId}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">{formatRelativeTime(activity.timestamp)}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card className="rounded-md border-border shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent Assigned Tickets</CardTitle>
              <CardDescription>Most recently updated tickets</CardDescription>
            </div>
            <Link href="/all-tickets" className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              View all
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-1">
            {recentAssigned.map((ticket) => (
              <Link
                key={ticket.id}
                href="/all-tickets"
                className="flex items-center gap-3 rounded-md px-2.5 py-3 transition-colors hover:bg-muted/50"
              >
                <Avatar className="h-9 w-9">
                  <AvatarFallback>{ticket.assignedTo.charAt(0)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {ticket.id} · {ticket.subject}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">Assigned to {ticket.assignedTo}</p>
                </div>
                <Badge variant={STATUS_COLOR[ticket.status].badge} className="shrink-0">
                  {ticket.status}
                </Badge>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
