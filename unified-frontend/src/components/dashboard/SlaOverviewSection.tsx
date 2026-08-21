"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Flame, PauseCircle, ShieldAlert, Timer } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModernStatCard } from "@/components/dashboard/ModernStatCard";
import { useDashboardSlaCounts, type DashboardSlaCounts } from "@tw/hooks/useDashboardSlaCounts";
import { getDashboardStats, type DashboardTicketSummary } from "@tw/api/ticket";
import { SlaBadge } from "@tw/components/sla/SlaBadge";

interface SlaOverviewSectionProps {
  // Optional — narrows this tile row to one client, within whatever
  // the caller's own role scope already allows. Passed down from
  // super-admin-dashboard.tsx's own Client filter.
  clientCompanyId?: string;
}

// GET /tickets/sla-overview-counts, one grouped server-side query
// under the caller's real visibility scoping (see
// useDashboardSlaCounts) — independent of the KPI cards above, which
// now also run on real backend data (see super-admin-dashboard.tsx),
// just fetched via a separate call with its own refresh cadence.
export function SlaOverviewSection({ clientCompanyId }: SlaOverviewSectionProps) {
  const { counts, isLoading } = useDashboardSlaCounts(clientCompanyId);

  // Same data source (and same real-ticket-id caveat) as the counts
  // above — GET /tickets/dashboard-stats, the identical endpoint the
  // ticket-workspace's own embedded Dashboard uses for its "Needs
  // Attention" card. Fetched independently here too, since that
  // embedded page is unreachable from this shell dashboard's own
  // routing (Super Admin/Site Lead/every other role lands here
  // instead) — this is the one place that page's real-data badges
  // actually get seen.
  const [criticalTickets, setCriticalTickets] = useState<DashboardTicketSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDashboardStats(clientCompanyId)
      .then((data) => {
        if (!cancelled) setCriticalTickets(data.critical_tickets);
      })
      .catch(() => {
        if (!cancelled) setCriticalTickets([]);
      });
    return () => {
      cancelled = true;
    };
  }, [clientCompanyId]);

  const items: Array<{
    key: keyof DashboardSlaCounts;
    title: string;
    subtitle?: string;
    icon: typeof Timer;
    tone: "default" | "success" | "warning" | "danger";
  }> = [
    { key: "running", title: "Running", subtitle: "Actively counting down", icon: Timer, tone: "default" },
    { key: "paused", title: "Paused", subtitle: "Waiting for Client / overridden", icon: PauseCircle, tone: "default" },
    { key: "atRisk", title: "At Risk", subtitle: "80%+ of target elapsed", icon: ShieldAlert, tone: "warning" },
    { key: "escalated", title: "Escalated", subtitle: "100% resolution time", icon: Flame, tone: "danger" },
    { key: "completed", title: "Completed", icon: CheckCircle2, tone: "success" },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-base">SLA Overview</CardTitle>
        <CardDescription>
          Live Resolution SLA state across real tickets, fetched independently of the KPI cards
          above (its own refresh cadence).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {items.map((item) => (
            <ModernStatCard
              key={item.key}
              title={item.title}
              value={isLoading ? "…" : counts[item.key]}
              subtitle={item.subtitle}
              icon={item.icon}
              tone={item.tone}
            />
          ))}
        </div>

        {criticalTickets && criticalTickets.length > 0 && (
          <div className="mt-6 border-t border-border pt-5">
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Needs Attention
            </h3>
            <ul className="flex flex-col gap-2">
              {criticalTickets.map((ticket) => (
                <li key={ticket.ticket_id}>
                  <Link
                    href={`/dashboard/tickets/${ticket.ticket_id}`}
                    className="flex items-center justify-between gap-3 rounded-md border border-border px-3.5 py-2.5 text-sm transition-colors hover:bg-muted/50"
                  >
                    <span className="min-w-0 flex-1 truncate font-medium">{ticket.title}</span>
                    <div className="flex flex-none items-center gap-1.5">
                      {ticket.resolution_sla_tier && ticket.resolution_sla_tier !== "healthy" && (
                        <SlaBadge tier={ticket.resolution_sla_tier} />
                      )}
                      <span className="text-xs text-muted-foreground">{ticket.current_priority}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
