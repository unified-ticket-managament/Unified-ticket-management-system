"use client";

import {
  Clock3,
  Download,
  FileSpreadsheet,
  FileText,
  Gauge,
  Printer,
  ShieldCheck,
  Ticket as TicketIcon,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { AreaTrendChart } from "@/components/shared/charts";
import { ModernBarListCard } from "@/components/dashboard/ModernBarListCard";
import { ModernStatCard } from "@/components/dashboard/ModernStatCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import {
  avgResponseMinutesFromAuditLogs,
  countsByCategoryFromTickets,
  countsByPriorityFromTickets,
  monthlyTrendFromTickets,
  reportMetricsFromTickets,
  staffPerformanceFromTickets,
  teamPerformanceFromTickets,
} from "@/lib/reportAggregations";
import { ROLE_NAMES } from "@/lib/role-access";
import { useAuthStore } from "@/store/auth-store";
import { listCategories } from "@tw/api/categories";
import { getAllTicketAuditLogs } from "@tw/api/auditLog";
import { listTickets } from "@tw/api/ticket";
import type { CategoryResponse, TicketAuditLogResponse, TicketResponse } from "@tw/types";

function downloadBlob(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function ReportsPage() {
  const { toast } = useToast();
  const currentUser = useAuthStore((s) => s.user);

  // No client-side role scoping needed here — listTickets()/
  // getAllTicketAuditLogs() already apply the real per-role visibility
  // scoping server-side (Account Manager -> own clients, Team Lead/
  // Staff -> own category, Site Lead/Super Admin -> everything), the
  // same as every other real ticket-workspace page.
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [categories, setCategories] = useState<CategoryResponse[]>([]);
  const [replyAddedLogs, setReplyAddedLogs] = useState<TicketAuditLogResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      listTickets(),
      listCategories(),
      getAllTicketAuditLogs({ eventType: "REPLY_ADDED" }),
    ])
      .then(([ticketsResult, categoriesResult, replyLogsResult]) => {
        if (cancelled) return;
        setTickets(ticketsResult);
        setCategories(categoriesResult);
        setReplyAddedLogs(replyLogsResult.items);
      })
      .catch(() => {
        if (!cancelled) {
          setTickets([]);
          setCategories([]);
          setReplyAddedLogs([]);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Super Admin/Site Lead/Account Manager keep Tickets by Category
  // (Account Manager's current behavior is deliberately unchanged);
  // Team Lead/Staff have it hidden per spec.
  const showCategoryChart =
    currentUser?.role !== ROLE_NAMES.TEAM_LEAD && currentUser?.role !== ROLE_NAMES.STAFF;

  const metrics = useMemo(() => reportMetricsFromTickets(tickets), [tickets]);
  const avgResponseMinutes = useMemo(
    () => avgResponseMinutesFromAuditLogs(tickets, replyAddedLogs),
    [tickets, replyAddedLogs]
  );
  const byPriority = useMemo(() => countsByPriorityFromTickets(tickets), [tickets]);
  const byCategory = useMemo(() => countsByCategoryFromTickets(tickets, categories), [tickets, categories]);
  const monthlyTrend = useMemo(() => monthlyTrendFromTickets(tickets), [tickets]);
  const staffPerformance = useMemo(() => staffPerformanceFromTickets(tickets), [tickets]);
  const teamPerformance = useMemo(() => teamPerformanceFromTickets(tickets), [tickets]);

  const buildRows = () => {
    const header = ["Ticket ID", "Subject", "Client", "Category", "Priority", "Status", "Assigned To", "Created Date", "Updated Date"];
    const rows = tickets.map((t) => [
      t.ticket_id,
      t.title,
      t.client_name ?? t.client_company_name ?? "—",
      t.ticket_type,
      t.current_priority,
      t.current_status,
      t.agent_name ?? "Unassigned",
      t.created_at,
      t.updated_at,
    ]);
    return { header, rows };
  };

  const handleExportCsv = () => {
    const { header, rows } = buildRows();
    const csv = [header, ...rows]
      .map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    downloadBlob(csv, `utms-report-${new Date().toISOString().slice(0, 10)}.csv`, "text/csv;charset=utf-8;");
    toast({ title: "CSV export ready", description: `${rows.length} ticket(s) exported.` });
  };

  const handleExportExcel = () => {
    const { header, rows } = buildRows();
    const table = `
      <table>
        <thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((r) => `<tr>${r.map((v) => `<td>${v}</td>`).join("")}</tr>`).join("")}</tbody>
      </table>`;
    downloadBlob(table, `utms-report-${new Date().toISOString().slice(0, 10)}.xls`, "application/vnd.ms-excel");
    toast({ title: "Excel export ready", description: `${rows.length} ticket(s) exported.` });
  };

  const handleExportPdf = () => {
    toast({ title: "Preparing PDF", description: "Use your browser's print dialog to save as PDF." });
    window.print();
  };

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Reports" }]} />

      <PageHeader
        title="Reports"
        description="Ticket volume, SLA compliance, and team performance across the organization."
        action={
          <div className="flex items-center gap-2 print:hidden">
            <Button variant="outline" className="gap-2" onClick={handleExportPdf}>
              <Printer className="h-4 w-4" />
              Export PDF
            </Button>
            <Button variant="outline" className="gap-2" onClick={handleExportExcel}>
              <FileSpreadsheet className="h-4 w-4" />
              Export Excel
            </Button>
            <Button variant="outline" className="gap-2" onClick={handleExportCsv}>
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
          </div>
        }
      />

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        <ModernStatCard title="Total Tickets" value={isLoading ? "…" : metrics.total} icon={TicketIcon} />
        <ModernStatCard title="Resolved Tickets" value={isLoading ? "…" : metrics.resolved} icon={ShieldCheck} tone="success" />
        <ModernStatCard title="Pending Tickets" value={isLoading ? "…" : metrics.pending} icon={Clock3} tone="warning" />
        <ModernStatCard title="Closed Tickets" value={isLoading ? "…" : metrics.closed} icon={FileText} />
        <ModernStatCard title="Avg. Resolution Time" value={isLoading ? "…" : `${metrics.avgResolutionHours}h`} icon={TrendingUp} />
        <ModernStatCard title="Avg. Response Time" value={isLoading ? "…" : `${avgResponseMinutes}m`} icon={Clock3} />
        <ModernStatCard
          title="SLA Compliance"
          value={isLoading ? "…" : `${metrics.slaCompliance}%`}
          icon={Gauge}
          tone={metrics.slaCompliance >= 90 ? "success" : "warning"}
        />
      </div>

      <Card className="rounded-md border-border shadow-sm">
        <CardHeader className="space-y-0">
          <CardTitle className="text-base">Monthly Ticket Trend</CardTitle>
          <CardDescription>Ticket volume over the last 6 months</CardDescription>
        </CardHeader>
        <CardContent>
          <AreaTrendChart data={monthlyTrend} valueFormatter={(v) => `${v} tickets`} />
        </CardContent>
      </Card>

      {/* "Tickets by Status" was removed per spec. Tickets by Category
          is role-gated (hidden for Team Lead/Staff); when it's hidden,
          Tickets by Priority expands to the full row instead of sharing
          a half-empty grid. */}
      {showCategoryChart ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <ModernBarListCard title="Tickets by Priority" data={byPriority} />
          <ModernBarListCard title="Tickets by Category" data={byCategory} />
        </div>
      ) : (
        <ModernBarListCard title="Tickets by Priority" data={byPriority} />
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <ModernBarListCard
          title="Staff Performance"
          description="Tickets resolved or closed per agent"
          data={staffPerformance}
        />
        <ModernBarListCard
          title="Team Performance"
          description="Tickets resolved or closed per category"
          data={teamPerformance}
        />
      </div>
    </div>
  );
}
