"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Flame, PauseCircle, ShieldAlert, Timer, TriangleAlert } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatCard } from "@/components/shared/stats";
import { listTickets } from "@tw/api/ticket";
import { useDashboardSlaCounts, type DashboardSlaCounts } from "@tw/hooks/useDashboardSlaCounts";
import type { TicketResponse } from "@tw/types";

// Deliberately independent of this dashboard's own `tickets` prop
// (MOCK_TICKETS / getTicketsFor***, see super-admin-dashboard.tsx) —
// those are fictional records with no real backend ticket_id, so the
// real GET /tickets/{id}/sla calls this section makes couldn't run
// against them at all. This fetches the real ticket list itself,
// entirely separately, so the existing mock-data KPIs/charts above are
// completely untouched by this addition.
//
// Modularity note (for when a real aggregation endpoint exists):
// useDashboardSlaCounts is the one and only place that currently does
// the N-calls-per-ticket client-side aggregation — this component only
// consumes its returned `DashboardSlaCounts` shape. Swapping that
// hook's internals for a single real aggregate-endpoint call (once the
// backend has one) requires no change here at all.
export function SlaOverviewSection() {
  const [tickets, setTickets] = useState<TicketResponse[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listTickets()
      .then((data) => {
        if (!cancelled) setTickets(data);
      })
      .catch(() => {
        if (!cancelled) setTickets([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { counts, isLoading } = useDashboardSlaCounts(tickets ?? []);

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
              value={tickets === null || isLoading ? "…" : counts[item.key]}
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
