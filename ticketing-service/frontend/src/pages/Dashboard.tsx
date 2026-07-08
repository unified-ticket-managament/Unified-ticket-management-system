import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  Inbox as InboxIcon,
  Lock,
  MailPlus,
  ShieldAlert,
  Ticket as TicketIcon,
  UserCheck,
} from "lucide-react";
import { AppLayout } from "@/components/layout/AppLayout";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { getInbox } from "@/api/inbox";
import { listTickets } from "@/api/ticket";
import { useToast } from "@/context/ToastContext";
import { useAuthContext } from "@/context/AuthContext";
import { formatDateTime } from "@/lib/format";
import { statusTone } from "@/lib/ticketTone";
import type { TicketResponse, TicketStatus } from "@/types";

const OPEN_STATUSES: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "PENDING",
  "WAITING_FOR_CLIENT",
];

// No SLA contract field exists on the ticket model yet, so "SLA Risk"
// is defined transparently here as a derived heuristic — open tickets
// that have gone untouched past this threshold — rather than a
// fabricated percentage.
const SLA_RISK_HOURS = 24;

function isToday(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

function hoursSince(iso: string) {
  return (Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60);
}

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
  const [tickets, setTickets] = useState<TicketResponse[]>([]);
  const [pendingInboxCount, setPendingInboxCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      try {
        const [ticketList, inbox] = await Promise.all([listTickets(), getInbox()]);
        if (cancelled) return;
        setTickets(ticketList);
        setPendingInboxCount(inbox.total);
      } catch (error) {
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
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const assignedCount = tickets.filter((t) => t.agent_id).length;
  const openCount = tickets.filter((t) => OPEN_STATUSES.includes(t.current_status)).length;
  const inProgressCount = tickets.filter((t) => t.current_status === "IN_PROGRESS").length;
  const resolvedCount = tickets.filter(
    (t) => t.current_status === "RESOLVED" || t.current_status === "CLOSED"
  ).length;
  const resolvedTodayCount = tickets.filter(
    (t) =>
      (t.current_status === "RESOLVED" || t.current_status === "CLOSED") &&
      isToday(t.updated_at)
  ).length;
  const closedCount = tickets.filter((t) => t.current_status === "CLOSED").length;
  const criticalCount = tickets.filter(
    (t) => t.current_priority === "HIGH" && OPEN_STATUSES.includes(t.current_status)
  ).length;
  const slaRiskCount = tickets.filter(
    (t) => OPEN_STATUSES.includes(t.current_status) && hoursSince(t.updated_at) >= SLA_RISK_HOURS
  ).length;

  const recentTickets = [...tickets]
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 6);

  const criticalTickets = tickets
    .filter((t) => t.current_priority === "HIGH" && OPEN_STATUSES.includes(t.current_status))
    .slice(0, 5);

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
            icon={<ShieldAlert size={19} className="text-warning" />}
            label="SLA Risk"
            value={slaRiskCount}
            tone="bg-warning/10"
            hint={`Open tickets untouched for ${SLA_RISK_HOURS}+ hours`}
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
                      <Badge tone={statusTone[ticket.current_status]}>
                        {ticket.current_status}
                      </Badge>
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
                        <Badge tone="danger">HIGH</Badge>
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
