"use client";

import Link from "next/link";
import {
  Archive,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Ticket,
} from "lucide-react";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { ModernBarListCard } from "@/components/dashboard/ModernBarListCard";
import { ModernStatCard } from "@/components/dashboard/ModernStatCard";
import { SlaOverviewSection } from "@/components/dashboard/SlaOverviewSection";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { countsByPriorityFromTickets } from "@/lib/reportAggregations";
import { cn, formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { getAllTicketAuditLogs } from "@tw/api/auditLog";
import { getDashboardStats, listTickets, type DashboardStats } from "@tw/api/ticket";
import { auditMetaFor } from "@tw/lib/auditLogMeta";
import type { TicketAuditLogResponse, TicketResponse, TicketStatus } from "@tw/types";

const STATUS_BADGE: Record<TicketStatus, { label: string; variant: "default" | "warning" | "success" | "secondary" }> = {
  OPEN: { label: "Open", variant: "default" },
  IN_PROGRESS: { label: "In Progress", variant: "warning" },
  PENDING: { label: "Pending", variant: "secondary" },
  WAITING_FOR_CLIENT: { label: "Waiting for Client", variant: "secondary" },
  RESOLVED: { label: "Resolved", variant: "success" },
  CLOSED: { label: "Closed", variant: "secondary" },
};

const AUDIT_TONE_CLASSES: Record<string, string> = {
  default: "bg-muted text-muted-foreground",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-destructive/10 text-destructive",
  info: "bg-info/10 text-info",
  accent: "bg-accent text-accent-foreground",
};

interface SuperAdminDashboardProps {
  description?: string;
}

// Super Admin's ticket-operations dashboard — replaces the generic
// ViewerDashboard for this role only (see dashboard/[[...slug]]/page.tsx).
// Every KPI/chart/list below is now bound to real backend data via the
// same @tw/api functions the embedded ticket workspace already uses
// (getDashboardStats/listTickets/getAllTicketAuditLogs) — all three
// already apply the real per-role visibility scoping server-side
// (Account Manager -> own clients, Team Lead/Staff -> own category,
// Site Lead/Super Admin -> everything), so this component no longer
// needs a role-scoped `tickets` prop at all; Account Manager/Team
// Lead/Staff's wrapper components (account-manager-dashboard.tsx etc.)
// just render this directly now.
export function SuperAdminDashboard({ description }: SuperAdminDashboardProps) {
  const currentUser = useAuthStore((state) => state.user);

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [recentActivity, setRecentActivity] = useState<TicketAuditLogResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      getDashboardStats(),
      listTickets(),
      getAllTicketAuditLogs({ limit: 8 }),
    ])
      .then(([statsResult, ticketsResult, activityResult]) => {
        if (cancelled) return;
        setStats(statsResult);
        setTickets(ticketsResult);
        setRecentActivity(activityResult.items);
      })
      .catch(() => {
        if (!cancelled) {
          setStats(null);
          setTickets([]);
          setRecentActivity([]);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const priorityBreakdown = countsByPriorityFromTickets(tickets);

  // "Recent Assigned Tickets" — real assigned tickets (agent_id present),
  // newest-updated first, so this reflects actual assignments/claims
  // rather than every recently-touched ticket regardless of ownership.
  const recentAssigned = [...tickets]
    .filter((t) => t.agent_id && t.agent_name)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 5);

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${currentUser?.name ?? "there"}`}
        description={description ?? "Ticket operations overview across the organization."}
      />

      {/* Top KPI row — deliberately only 4 tiles (Open/Resolved Today/
          In Progress/Closed), all sourced from the real GET
          /tickets/dashboard-stats endpoint. SLA Breaches and Escalated
          Tickets are intentionally absent from this row — both are
          still fully live just below, as the real "Breached"/
          "Escalated" tiles in SlaOverviewSection. */}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <ModernStatCard title="Open Tickets" value={isLoading ? "…" : stats?.open ?? 0} subtitle="Awaiting first response" icon={Ticket} />
        <ModernStatCard
          title="Resolved Today"
          value={isLoading ? "…" : stats?.resolved_today ?? 0}
          subtitle="Resolved so far today"
          icon={CheckCircle2}
          tone="success"
        />
        <ModernStatCard title="In Progress" value={isLoading ? "…" : stats?.in_progress ?? 0} subtitle="Actively being worked" icon={Clock} tone="warning" />
        <ModernStatCard title="Closed" value={isLoading ? "…" : stats?.closed ?? 0} subtitle="All-time closed" icon={Archive} />
      </div>

      <SlaOverviewSection />

      {/* "Tickets by Status" was removed per spec — Tickets by Priority
          now takes the full width instead of sharing a 2-col grid with
          a chart that no longer exists. */}
      <ModernBarListCard
        title="Tickets by Priority"
        description="Current workload by priority level"
        data={priorityBreakdown}
        legend={priorityBreakdown.map((d) => ({ label: d.label, dotClassName: d.color ?? "bg-blue-500" }))}
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card className="rounded-md border-border shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent Activity</CardTitle>
              <CardDescription>Latest ticket actions across the team</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-1">
            {recentActivity.length === 0 && !isLoading && (
              <p className="px-2.5 py-3 text-sm text-muted-foreground">No recent activity.</p>
            )}
            {recentActivity.map((log) => {
              const meta = auditMetaFor(log.event_type);
              return (
                <div key={log.audit_id} className="flex items-start gap-3 rounded-md px-2.5 py-3 transition-colors hover:bg-muted/50">
                  <div className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm", AUDIT_TONE_CLASSES[meta.tone])}>
                    <span aria-hidden="true">{meta.icon}</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">
                      <span className="font-medium">{log.actor_name}</span>{" "}
                      <span className="text-muted-foreground">{meta.label}</span>{" "}
                      <span className="font-medium">— {log.ticket_title}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">{formatRelativeTime(log.created_at)}</p>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        <Card className="rounded-md border-border shadow-sm">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">Recent Assigned Tickets</CardTitle>
              <CardDescription>Most recently updated assignments</CardDescription>
            </div>
            <Link href="/all-tickets" className="flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              View all
              <ArrowUpRight className="h-3.5 w-3.5" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-1">
            {recentAssigned.length === 0 && !isLoading && (
              <p className="px-2.5 py-3 text-sm text-muted-foreground">No assigned tickets yet.</p>
            )}
            {recentAssigned.map((ticket) => (
              <Link
                key={ticket.ticket_id}
                href="/all-tickets"
                className="flex items-center gap-3 rounded-md px-2.5 py-3 transition-colors hover:bg-muted/50"
              >
                <Avatar className="h-9 w-9">
                  <AvatarFallback>{(ticket.agent_name ?? "?").charAt(0)}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{ticket.title}</p>
                  <p className="truncate text-xs text-muted-foreground">Assigned to {ticket.agent_name}</p>
                </div>
                <Badge variant={STATUS_BADGE[ticket.current_status].variant} className="shrink-0">
                  {STATUS_BADGE[ticket.current_status].label}
                </Badge>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
