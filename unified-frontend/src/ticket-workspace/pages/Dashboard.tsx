import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  Flame,
  Inbox as InboxIcon,
  Lock,
  MailPlus,
  PauseCircle,
  ShieldAlert,
  Ticket as TicketIcon,
  Timer,
  UserCheck,
} from "lucide-react";
import { AppLayout } from "@tw/components/layout/AppLayout";
import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { SlaBadge } from "@tw/components/sla/SlaBadge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { getViewCounts } from "@tw/api/inbox";
import { getDashboardStats, type DashboardStats } from "@tw/api/ticket";
import { useDashboardSlaCounts } from "@tw/hooks/useDashboardSlaCounts";
import { useToast } from "@tw/context/ToastContext";
import { useAuthContext } from "@tw/context/AuthContext";
import { formatDateTime } from "@tw/lib/format";
import { statusTone } from "@tw/lib/ticketTone";

// No SLA contract field exists on the ticket model yet, so "SLA Risk"
// is defined transparently here as a derived heuristic — open tickets
// that have gone untouched past this threshold — rather than a
// fabricated percentage. Computed server-side now (see
const SLA_RISK_HOURS = 24;

const EMPTY_STATS: DashboardStats = {
  assigned: 0,
  open: 0,
  in_progress: 0,
  resolved: 0,
  resolved_today: 0,
  closed: 0,
  critical: 0,
  sla_risk: 0,
  recent_tickets: [],
  critical_tickets: [],
};
function StatCard({
  icon,
  label,
  value,
  tone,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  tone: string;
  hint?: string;
}) {
  return (
    <div
      title={hint}
      className="rounded-md2 border border-border bg-surface p-5 shadow-xs transition-all duration-200 hover:-translate-y-0.5 hover:shadow-cardHover"
    >
      <div className="flex items-center gap-3.5">
        <div className={`flex h-11 w-11 flex-none items-center justify-center rounded-md2 ${tone}`}>
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-[26px] font-bold leading-none tracking-tight text-slate-900">
            {value}
          </p>
          <p className="mt-1.5 truncate text-xs font-medium text-muted">{label}</p>
        </div>
      </div>
    </div>
  );
}

function QuickAction({
  to,
  icon,
  label,
  description,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  description: string;
}) {
  return (
    <Link
      to={to}
      className="group flex items-center gap-3 rounded-md2 border border-border bg-surface px-4 py-3.5 transition-all duration-150 hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-cardHover"
    >
      <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-accent/10 text-accent">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold text-slate-900">{label}</p>
        <p className="truncate text-[11px] text-muted">{description}</p>
      </div>
      <ChevronRight
        size={15}
        className="flex-none text-muted/60 transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
      />
    </Link>
  );
}

export function Dashboard() {
  const { pushToast } = useToast();
  const { currentUser } = useAuthContext();
  const [stats, setStats] = useState<DashboardStats>(EMPTY_STATS);
  const [pendingInboxCount, setPendingInboxCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  // Independent of the bounded getDashboardStats()/getViewCounts()
  // calls above — one grouped GET /tickets/sla-overview-counts query
  // (see useDashboardSlaCounts, also used by the shell's own
  // SlaOverviewSection, src/components/dashboard/). Kept separate from
  // `stats` deliberately: this endpoint has its own refresh cadence and
  // its own loading state.
  const { counts: slaCounts } = useDashboardSlaCounts();

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      setIsLoading(true);
      try {
        // Both bounded/grouped server-side queries now — this used to
        // be listTickets() (every visible ticket, unbounded) plus
        // getInbox() (the entire pending queue, just to read
        // `.total`). Neither scales with total ticket/mail count
        // anymore; both cost a fixed, small amount of work regardless.
        const [dashboardStats, viewCounts] = await Promise.all([
          getDashboardStats(controller.signal),
          getViewCounts(),
        ]);
        if (cancelled) return;
        setStats(dashboardStats);
        setPendingInboxCount(viewCounts.pending);
      } catch (error) {
        if (cancelled || (error instanceof Error && error.name === "CanceledError")) return;
        pushToast(
          error instanceof Error ? error.message : "Failed to load dashboard.",
          "error"
        );
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const {
    assigned: assignedCount,
    open: openCount,
    in_progress: inProgressCount,
    resolved: resolvedCount,
    resolved_today: resolvedTodayCount,
    closed: closedCount,
    critical: criticalCount,
    sla_risk: slaRiskCount,
    recent_tickets: recentTickets,
    critical_tickets: criticalTickets,
  } = stats;

  const funnelStages = [
    { label: "Pending Inbox", count: pendingInboxCount },
    { label: "Ticket Created", count: openCount + inProgressCount + resolvedCount },
    { label: "In Progress", count: inProgressCount },
    { label: "Resolved", count: resolvedCount },
  ];
  const funnelMax = Math.max(1, ...funnelStages.map((s) => s.count));

  return (
    <AppLayout title="Dashboard" description={`Your workspace overview, ${currentUser?.name}.`}>
      <div className="flex flex-col gap-7">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <StatCard
            icon={<InboxIcon size={19} className="text-warning" />}
            label="Pending Inbox"
            value={pendingInboxCount}
            tone="bg-warning/10"
          />
          <StatCard
            icon={<UserCheck size={19} className="text-accent" />}
            label="Assigned Tickets"
            value={assignedCount}
            tone="bg-accent/10"
          />
          <StatCard
            icon={<TicketIcon size={19} className="text-info" />}
            label="Open Tickets"
            value={openCount}
            tone="bg-info/10"
          />
          <StatCard
            icon={<AlertTriangle size={19} className="text-danger" />}
            label="Critical Tickets"
            value={criticalCount}
            tone="bg-danger/10"
            hint="High priority tickets still open"
          />
          <StatCard
            icon={<CheckCircle2 size={19} className="text-success" />}
            label="Resolved Today"
            value={resolvedTodayCount}
            tone="bg-success/10"
          />
          <StatCard
            icon={<Archive size={19} className="text-success" />}
            label="Tickets Resolved"
            value={resolvedCount}
            tone="bg-success/10"
            hint="All-time resolved or closed tickets"
          />
          <StatCard
            icon={<Lock size={19} className="text-slate-600" />}
            label="Closed Tickets"
            value={closedCount}
            tone="bg-slate-500/10"
            hint="All-time tickets marked closed"
          />
        </div>

        <div>
          <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
            SLA Overview
          </p>
          {/* Server-aggregated via GET /tickets/sla-overview-counts —
              see useDashboardSlaCounts. */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard
              icon={<Timer size={19} className="text-accent" />}
              label="Running"
              value={slaCounts.running}
              tone="bg-accent/10"
              hint="Resolution SLA actively counting down"
            />
            <StatCard
              icon={<PauseCircle size={19} className="text-slate-600" />}
              label="Paused"
              value={slaCounts.paused}
              tone="bg-slate-500/10"
              hint="Waiting for Client, or manually overridden"
            />
            <StatCard
              icon={<ShieldAlert size={19} className="text-warning" />}
              label="At Risk"
              value={slaCounts.atRisk}
              tone="bg-warning/10"
              hint="80% or more of the resolution target elapsed"
            />
            <StatCard
              icon={<AlertTriangle size={19} className="text-danger" />}
              label="Breached"
              value={slaCounts.breached}
              tone="bg-danger/10"
              hint="Past the resolution target"
            />
            <StatCard
              icon={<Flame size={19} className="text-danger" />}
              label="Escalated"
              value={slaCounts.escalated}
              tone="bg-danger/10"
              hint="150% or more of the resolution target elapsed"
            />
            <StatCard
              icon={<CheckCircle2 size={19} className="text-success" />}
              label="Completed"
              value={slaCounts.completed}
              tone="bg-success/10"
              hint="Resolution SLA ended — ticket was closed"
            />
          </div>
        </div>

        <div className={`grid grid-cols-1 gap-3 ${currentUser?.role === "Site Lead" ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
          {currentUser?.role === "Site Lead" && (
            <QuickAction
              to="/create-mail"
              icon={<MailPlus size={17} />}
              label="Create Dummy Mail"
              description="Simulate an incoming client email"
            />
          )}
          <QuickAction
            to="/inbox"
            icon={<InboxIcon size={17} />}
            label="Go to Inbox"
            description={`${pendingInboxCount} waiting for triage`}
          />
          <QuickAction
            to="/tickets"
            icon={<TicketIcon size={17} />}
            label="View Tickets"
            description={`${openCount} currently open`}
          />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_0.7fr]">
          <Card title="Recent Activity" eyebrow="Latest updates">
            {isLoading ? (
              <SkeletonRows rows={5} />
            ) : recentTickets.length === 0 ? (
              <EmptyState
                icon="🗂️"
                title="No tickets yet"
                description="Tickets created from inbox emails will show up here."
              />
            ) : (
              <ul className="flex flex-col divide-y divide-border">
                {recentTickets.map((ticket) => (
                  <li key={ticket.ticket_id} className="py-3 first:pt-0 last:pb-0">
                    <Link
                      to={`/tickets/${ticket.ticket_id}`}
                      className="-mx-2.5 flex items-center justify-between gap-3 rounded-md2 px-2.5 py-2 transition-colors hover:bg-surfaceHover"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-slate-900">
                          {ticket.title}
                        </p>
                        <p className="mt-0.5 text-[11px] text-muted">
                          {ticket.client_name ?? "Unknown client"} · Updated{" "}
                          {formatDateTime(ticket.updated_at)}
                        </p>
                      </div>
                      <div className="flex flex-none items-center gap-1.5">
                        {ticket.resolution_sla_tier && ticket.resolution_sla_tier !== "healthy" && (
                          <SlaBadge tier={ticket.resolution_sla_tier} />
                        )}
                        <Badge tone={statusTone[ticket.current_status]}>
                          {ticket.current_status}
                        </Badge>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="flex flex-col gap-6">
            <Card title="Workflow Summary" eyebrow="Pipeline">
              <div className="flex flex-col gap-4">
                {funnelStages.map((stage, index) => (
                  <div key={stage.label} className="flex items-center gap-3">
                    <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent/10 text-[10px] font-bold text-accent">
                      {index + 1}
                    </div>
                    <div className="flex-1">
                      <div className="mb-1 flex items-center justify-between">
                        <p className="text-xs font-medium text-slate-700">{stage.label}</p>
                        <p className="text-xs font-semibold text-slate-900">{stage.count}</p>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas">
                        <div
                          className="h-full rounded-full bg-accent transition-all duration-500"
                          style={{ width: `${(stage.count / funnelMax) * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Needs Attention" eyebrow="High priority · open">
              {criticalTickets.length === 0 ? (
                <p className="py-2 text-center text-xs text-muted">
                  No critical tickets right now.
                </p>
              ) : (
                <ul className="flex flex-col gap-2.5">
                  {criticalTickets.map((ticket) => (
                    <li key={ticket.ticket_id}>
                      <Link
                        to={`/tickets/${ticket.ticket_id}`}
                        className="flex items-center justify-between gap-2 rounded-md2 border border-danger/15 bg-danger/5 px-3 py-2 transition-colors hover:bg-danger/10"
                      >
                        <span className="truncate text-xs font-medium text-slate-800">
                          {ticket.title}
                        </span>
                        <div className="flex flex-none items-center gap-1.5">
                          {ticket.resolution_sla_tier && ticket.resolution_sla_tier !== "healthy" && (
                            <SlaBadge tier={ticket.resolution_sla_tier} />
                          )}
                          <Badge tone="danger">HIGH</Badge>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
