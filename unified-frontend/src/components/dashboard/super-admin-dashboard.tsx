"use client";

import Link from "next/link";
import {
  Archive,
  ArrowUpCircle,
  ArrowUpRight,
  BarChart3,
  Bell,
  CheckCircle2,
  Clock,
  FileBarChart,
  Loader2,
  Ticket,
  TriangleAlert,
  UserCog,
} from "lucide-react";
import { useMemo } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { CategoryBarList } from "@/components/shared/charts";
import { StatCard } from "@/components/shared/stats";
import { SlaOverviewSection } from "@/components/dashboard/SlaOverviewSection";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getCountsByPriority,
  getCountsByStatus,
  getDashboardKpis,
  MOCK_DASHBOARD_NOTIFICATIONS,
  MOCK_RECENT_ACTIVITIES,
  MOCK_TICKETS,
  PRIORITY_COLOR,
  STATUS_COLOR,
} from "@/lib/mock-tickets";
import { formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import type { MockTicket } from "@/lib/mock-tickets";

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
  const priorityBreakdown = useMemo(() => getCountsByPriority(tickets), [tickets]);
  const statusBreakdown = useMemo(() => getCountsByStatus(tickets), [tickets]);

  const recentAssigned = useMemo(
    () =>
      [...tickets]
        .sort((a, b) => new Date(b.updatedDate).getTime() - new Date(a.updatedDate).getTime())
        .slice(0, 5),
    [tickets]
  );

  const quickActions = [
    {
      title: "Create Ticket",
      description: "Log a new ticket on behalf of a client.",
      href: "/all-tickets",
      icon: Ticket,
    },
    {
      title: "Assign Ticket",
      description: "Assign or reassign tickets to an owner.",
      href: "/all-tickets",
      icon: UserCog,
    },
    {
      title: "Manage Users",
      description: "Add or update agents and their roles.",
      href: "/users",
      icon: UserCog,
    },
    {
      title: "Generate Report",
      description: "Export SLA and volume reports.",
      href: "/reports",
      icon: FileBarChart,
    },
  ];

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${currentUser?.name ?? "there"}`}
        description={description ?? "Ticket operations overview across the organization."}
      />

      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard title="Open Tickets" value={kpis.open} subtitle="Awaiting first response" icon={Ticket} />
        <StatCard
          title="Resolved Today"
          value={kpis.resolvedToday}
          subtitle="Closed within SLA"
          icon={CheckCircle2}
          tone="success"
        />
        <StatCard title="In Progress" value={kpis.inProgress} subtitle="Actively being worked" icon={Clock} tone="warning" />
        <StatCard title="Closed" value={kpis.closed} subtitle="All-time closed" icon={Archive} />
        <StatCard
          title="SLA Breaches"
          value={kpis.slaBreaches}
          subtitle="Past response deadline"
          icon={TriangleAlert}
          tone="danger"
        />
        <StatCard
          title="Escalated Tickets"
          value={kpis.escalated}
          subtitle="Sent to Tier 2 support"
          icon={ArrowUpCircle}
          tone="warning"
        />
      </div>

      <SlaOverviewSection />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tickets by Priority</CardTitle>
            <CardDescription>Current open workload by priority level</CardDescription>
          </CardHeader>
          <CardContent>
            <CategoryBarList data={priorityBreakdown} />
            <div className="mt-4 flex flex-wrap gap-3">
              {Object.entries(PRIORITY_COLOR).map(([label, { bar }]) => (
                <span key={label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={`h-2 w-2 rounded-full ${bar}`} />
                  {label}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tickets by Status</CardTitle>
            <CardDescription>Distribution across the ticket lifecycle</CardDescription>
          </CardHeader>
          <CardContent>
            <CategoryBarList data={statusBreakdown} />
            <div className="mt-4 flex flex-wrap gap-3">
              {Object.entries(STATUS_COLOR).map(([label, { bar }]) => (
                <span key={label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={`h-2 w-2 rounded-full ${bar}`} />
                  {label}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">Quick Actions</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <Link key={action.title} href={action.href}>
                <Card className="group h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-md">
                  <CardContent className="flex items-start gap-3 p-5">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium">{action.title}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">{action.description}</p>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent Activities</CardTitle>
              <CardDescription>Latest ticket actions across the team</CardDescription>
            </div>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-1">
            {MOCK_RECENT_ACTIVITIES.map((activity) => (
              <div key={activity.id} className="flex items-start gap-3 rounded-lg px-2 py-2.5">
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

        <Card>
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
                className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50"
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

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="text-base">Recent Notifications</CardTitle>
            <CardDescription>System alerts from the last few hours</CardDescription>
          </div>
          <Bell className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent className="space-y-1">
          {MOCK_DASHBOARD_NOTIFICATIONS.map((notification) => (
            <div key={notification.id} className="flex items-start gap-3 rounded-lg px-2 py-2.5">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                <Bell className="h-4 w-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{notification.title}</p>
                <p className="text-xs text-muted-foreground">{notification.description}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">{notification.time}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
