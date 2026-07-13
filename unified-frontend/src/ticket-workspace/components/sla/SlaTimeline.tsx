"use client";

import { useEffect, useState } from "react";
import { Card } from "@tw/components/common/Card";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { getTicketAuditLogs } from "@tw/api/auditLog";
import { formatDateTime } from "@tw/lib/format";
import type { AuditEventType, AuditLogResponse } from "@tw/types";

// There is no single "SLA timeline" endpoint — this derives one from
// the ticket's existing, already-verified audit trail
// (GET /tickets/{id}/audit-logs, which the backend documents as
// including both direct ticket events and events logged against the
// ticket's own interactions — e.g. EMAIL_RECEIVED from the interaction
// that started this ticket). Filtered to the subset that's actually
// SLA-relevant rather than showing every note/attachment/claim event
// too.
const RELEVANT_EVENT_TYPES = new Set<AuditEventType>([
  "EMAIL_RECEIVED",
  "TICKET_CREATED",
  "STATUS_CHANGED",
  "PRIORITY_CHANGED",
  "SLA_MANUALLY_PAUSED",
  "SLA_MANUALLY_RESUMED",
  "SLA_BREACH_DETECTED",
  "SLA_ESCALATED",
]);

const DOT_CLASSES: Record<string, string> = {
  neutral: "bg-accent",
  at_risk: "bg-warning",
  breached: "bg-danger",
  escalated: "bg-danger",
};

function describeEvent(log: AuditLogResponse): { label: string; tone: keyof typeof DOT_CLASSES } {
  switch (log.event_type) {
    case "EMAIL_RECEIVED":
      return { label: "Email received — First Response SLA started", tone: "neutral" };
    case "TICKET_CREATED":
      return { label: "Ticket created — Resolution SLA started", tone: "neutral" };
    case "PRIORITY_CHANGED":
      return { label: "Priority changed — Resolution deadline reshifted", tone: "neutral" };
    case "STATUS_CHANGED": {
      const newStatus = log.new_values?.current_status;
      const oldStatus = log.old_values?.current_status;
      if (newStatus === "WAITING_FOR_CLIENT") {
        return { label: "Status → Waiting for Client — Resolution SLA paused", tone: "at_risk" };
      }
      if (oldStatus === "WAITING_FOR_CLIENT") {
        return { label: "Left Waiting for Client — Resolution SLA resumed", tone: "neutral" };
      }
      if (newStatus === "CLOSED") {
        return { label: "Ticket closed — Resolution SLA completed", tone: "neutral" };
      }
      return { label: `Status changed to ${newStatus ?? "?"}`, tone: "neutral" };
    }
    case "SLA_MANUALLY_PAUSED":
      return { label: "SLA manually paused by a supervisor", tone: "at_risk" };
    case "SLA_MANUALLY_RESUMED":
      return { label: "SLA manually resumed by a supervisor", tone: "neutral" };
    case "SLA_BREACH_DETECTED":
      return { label: "Resolution SLA breached (sweep-detected)", tone: "breached" };
    case "SLA_ESCALATED":
      return { label: "Resolution SLA escalated (sweep-detected)", tone: "escalated" };
    default:
      return { label: log.event_type.replace(/_/g, " "), tone: "neutral" };
  }
}

export function SlaTimeline({ ticketId }: { ticketId: string }) {
  const [logs, setLogs] = useState<AuditLogResponse[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLogs(null);
    getTicketAuditLogs(ticketId)
      .then((data) => {
        if (!cancelled) setLogs(data);
      })
      .catch(() => {
        if (!cancelled) setLogs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ticketId]);

  if (logs === null) {
    return (
      <Card title="SLA Timeline" eyebrow="Audit trail">
        <SkeletonRows rows={4} />
      </Card>
    );
  }

  const events = logs
    .filter((log) => RELEVANT_EVENT_TYPES.has(log.event_type))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  return (
    <Card title="SLA Timeline" eyebrow="Audit trail">
      {events.length === 0 ? (
        <p className="text-xs text-muted">No SLA-related events recorded yet.</p>
      ) : (
        <ol className="flex flex-col gap-4">
          {events.map((log) => {
            const { label, tone } = describeEvent(log);
            return (
              <li key={log.audit_id} className="flex gap-3">
                <span className={`mt-1 h-2 w-2 flex-none rounded-full ${DOT_CLASSES[tone]}`} />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-slate-800">{label}</p>
                  <p className="mt-0.5 text-[11px] text-muted">
                    {formatDateTime(log.created_at)} · {log.actor_name}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
