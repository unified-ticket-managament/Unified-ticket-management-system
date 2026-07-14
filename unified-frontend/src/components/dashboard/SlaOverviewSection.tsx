"use client";

import { CheckCircle2, Flame, PauseCircle, ShieldAlert, Timer, TriangleAlert } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatCard } from "@/components/shared/stats";
import { useDashboardSlaCounts, type DashboardSlaCounts } from "@tw/hooks/useDashboardSlaCounts";

// Deliberately independent of this dashboard's own `tickets` prop
// (MOCK_TICKETS / getTicketsFor***, see super-admin-dashboard.tsx) —
// those are fictional records with no real backend ticket_id, so a
// real per-ticket SLA lookup couldn't run against them at all.
// useDashboardSlaCounts calls GET /tickets/sla-overview-counts, one
// grouped server-side query under the caller's real visibility
// scoping, entirely independent of the mock-data KPIs/charts above.
export function SlaOverviewSection() {
  const { counts, isLoading } = useDashboardSlaCounts();

  const items: Array<{
    key: keyof DashboardSlaCounts;
    title: string;
    subtitle: string;
    icon: typeof Timer;
    tone: "default" | "success" | "warning" | "danger";
  }> = [
    { key: "running", title: "Running", subtitle: "Actively counting down", icon: Timer, tone: "default" },
    { key: "paused", title: "Paused", subtitle: "Waiting for Client / overridden", icon: PauseCircle, tone: "default" },
    { key: "atRisk", title: "At Risk", subtitle: "80%+ of target elapsed", icon: ShieldAlert, tone: "warning" },
    { key: "breached", title: "Breached", subtitle: "Past the resolution target", icon: TriangleAlert, tone: "danger" },
    { key: "escalated", title: "Escalated", subtitle: "150%+ of target elapsed", icon: Flame, tone: "danger" },
    { key: "completed", title: "Completed", subtitle: "Ticket closed", icon: CheckCircle2, tone: "success" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">SLA Overview</CardTitle>
        <CardDescription>
          Live Resolution SLA state across real tickets — independent of the KPI cards above,
          which still run on this dashboard&apos;s existing mock dataset.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {items.map((item) => (
            <StatCard
              key={item.key}
              title={item.title}
              value={isLoading ? "…" : counts[item.key]}
              subtitle={item.subtitle}
              icon={item.icon}
              tone={item.tone}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
