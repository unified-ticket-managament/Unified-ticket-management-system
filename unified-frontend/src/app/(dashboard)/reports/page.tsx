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
import { useMemo } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { AreaTrendChart } from "@/components/shared/charts";
import { ModernBarListCard } from "@/components/dashboard/ModernBarListCard";
import { ModernStatCard } from "@/components/dashboard/ModernStatCard";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";
import {
  getCountsByCategory,
  getCountsByPriority,
  getCountsByStatus,
  getReportMetrics,
  getStaffPerformance,
  getTeamPerformance,
  getTicketsForAccountManager,
  getTicketsForStaff,
  getTicketsForTeamLead,
  MONTHLY_TICKET_TREND,
} from "@/lib/mock-tickets";
import { ROLE_NAMES } from "@/lib/role-access";
import { useMockTicketsStore } from "@/store/mock-tickets-store";
import { useAuthStore } from "@/store/auth-store";

// Chart-only semantic color remap for the reference design — see the
// matching comment in super-admin-dashboard.tsx for why this is kept
// local to each page rather than written back into lib/mock-tickets.ts.
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
const CATEGORY_CHART_COLOR_CYCLE = ["bg-blue-500", "bg-orange-500", "bg-green-500", "bg-purple-500", "bg-red-500", "bg-gray-400"];

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
  const allTickets = useMockTicketsStore((s) => s.tickets);

  // Same report layout for every role (per spec) — only which
  // tickets feed it differs: Account Manager/Team Lead/Staff each see
  // reports scoped to their own data (see the matching
  // getTicketsForXxx helpers in lib/mock-tickets.ts); Super Admin/
  // Site Lead/anyone else keep the unscoped, organization-wide set.
  const tickets = useMemo(() => {
    if (!currentUser) return allTickets;
    switch (currentUser.role) {
      case ROLE_NAMES.ACCOUNT_MANAGER:
        return getTicketsForAccountManager(currentUser.user_id, allTickets);
      case ROLE_NAMES.TEAM_LEAD:
        return getTicketsForTeamLead(currentUser.user_id, allTickets);
      case ROLE_NAMES.STAFF:
        return getTicketsForStaff(currentUser.user_id, allTickets);
      default:
        return allTickets;
    }
  }, [allTickets, currentUser]);

  const metrics = useMemo(() => getReportMetrics(tickets), [tickets]);
  const byStatus = useMemo(
    () => getCountsByStatus(tickets).map((d) => ({ ...d, color: STATUS_CHART_COLOR[d.label] ?? d.color })),
    [tickets]
  );
  const byPriority = useMemo(
    () => getCountsByPriority(tickets).map((d) => ({ ...d, color: PRIORITY_CHART_COLOR[d.label] ?? d.color })),
    [tickets]
  );
  const byCategory = useMemo(
    () =>
      getCountsByCategory(tickets).map((d, i) => ({
        ...d,
        color: CATEGORY_CHART_COLOR_CYCLE[i % CATEGORY_CHART_COLOR_CYCLE.length],
      })),
    [tickets]
  );
  const staffPerformance = useMemo(() => getStaffPerformance(tickets), [tickets]);
  const teamPerformance = useMemo(() => getTeamPerformance(tickets), [tickets]);

  const buildRows = () => {
    const header = ["Ticket ID", "Subject", "Client", "Category", "Priority", "Status", "Assigned To", "Created Date", "Updated Date"];
    const rows = tickets.map((t) => [t.id, t.subject, t.client, t.category, t.priority, t.status, t.assignedTo, t.createdDate, t.updatedDate]);
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
        <ModernStatCard title="Total Tickets" value={metrics.total} icon={TicketIcon} />
        <ModernStatCard title="Resolved Tickets" value={metrics.resolved} icon={ShieldCheck} tone="success" />
        <ModernStatCard title="Pending Tickets" value={metrics.pending} icon={Clock3} tone="warning" />
        <ModernStatCard title="Closed Tickets" value={metrics.closed} icon={FileText} />
        <ModernStatCard title="Avg. Resolution Time" value={`${metrics.avgResolutionHours}h`} icon={TrendingUp} />
        <ModernStatCard title="Avg. Response Time" value={`${metrics.avgResponseMinutes}m`} icon={Clock3} />
        <ModernStatCard title="SLA Compliance" value={`${metrics.slaCompliance}%`} icon={Gauge} tone={metrics.slaCompliance >= 90 ? "success" : "warning"} />
      </div>

      <Card className="rounded-md border-border shadow-sm">
        <CardHeader className="space-y-0">
          <CardTitle className="text-base">Monthly Ticket Trend</CardTitle>
          <CardDescription>Ticket volume over the last 6 months</CardDescription>
        </CardHeader>
        <CardContent>
          <AreaTrendChart data={MONTHLY_TICKET_TREND} valueFormatter={(v) => `${v} tickets`} />
        </CardContent>
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <ModernBarListCard title="Tickets by Status" data={byStatus} />
        <ModernBarListCard title="Tickets by Priority" data={byPriority} />
        <ModernBarListCard title="Tickets by Category" data={byCategory} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <ModernBarListCard
          title="Staff Performance"
          description="Tickets resolved or closed per agent"
          data={staffPerformance}
        />
        <ModernBarListCard
          title="Team Performance"
          description="Tickets resolved or closed per team"
          data={teamPerformance}
        />
      </div>
    </div>
  );
}
