import { useEffect, useRef, useState } from "react";
import { Lock } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { getTicketAuditLogs } from "@tw/api/auditLog";
import { auditMetaFor, diffFields, formatFieldValue, humanizeFieldKey } from "@tw/lib/auditLogMeta";
import { formatDateTime } from "@tw/lib/format";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { ActorRole } from "@tw/types";

const POLL_INTERVAL_MS = 10_000;

const ACTOR_ROLE_LABEL: Record<ActorRole, string> = {
  AGENT: "Agent",
  CLIENT: "Client",
  SYSTEM: "System",
};

interface TicketAuditLogProps {
  // Bumped by the parent right after an action this agent took
  // completes, so the trail updates immediately instead of waiting
  // for the next poll tick.
  refreshToken?: number;
  // Rendered inside TicketActivityPanel's tabbed box, which already
  // provides the outer border/shadow — see Card's `flat` prop.
  flat?: boolean;
}

export function TicketAuditLog({ refreshToken, flat = false }: TicketAuditLogProps) {
  const { activeTicket } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const ticketId = activeTicket?.ticket_id;

  // Mirrors the backend's own gate exactly (InteractionService.
  // get_ticket_audit_logs -> ensure_agent_can_view_ticket_including_
  // escalated): ticket:view_audit_trail, OR ticket:view_escalated
  // while the ticket currently has an active escalation. Reaching
  // this tab at all already implies ordinary/escalation-widened
  // ticket visibility (TicketService.get_by_id runs the identical
  // check before the ticket ever loads), so those two permissions are
  // the only remaining variables — is_escalated is the same
  // escalation-repository fact the backend checks, just already
  // attached to the ticket the page loaded. Purely additive
  // defense-in-depth: the backend still enforces this on every real
  // fetch regardless of this check.
  const canViewAuditTrail =
    !!currentUser?.permissions.includes("ticket:view_audit_trail") ||
    (!!currentUser?.permissions.includes("ticket:view_escalated") &&
      !!activeTicket?.is_escalated);

  const [entries, setEntries] = useState<
    Awaited<ReturnType<typeof getTicketAuditLogs>>
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!ticketId || !canViewAuditTrail) return;

    let cancelled = false;
    const thisRequestId = ++requestIdRef.current;

    async function load(showLoading: boolean) {
      if (showLoading) setIsLoading(true);
      try {
        const data = await getTicketAuditLogs(ticketId!);
        if (!cancelled && thisRequestId === requestIdRef.current) {
          setEntries(data);
        }
      } catch {
        // Silent on poll failures — the panel just keeps showing
        // the last good data rather than flashing an error toast
        // every 10 seconds.
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load(true);
    // Skip poll ticks while the browser tab is backgrounded — no
    // point hitting the backend every 10s for a panel nobody can
    // see — and catch up with one immediate refetch the moment it
    // becomes visible again instead of waiting for the next tick.
    const interval = window.setInterval(() => {
      if (document.hidden) return;
      load(false);
    }, POLL_INTERVAL_MS);

    function handleVisibilityChange() {
      if (!document.hidden) load(false);
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, refreshToken, canViewAuditTrail]);

  return (
    <Card
      flat={flat}
      title="Audit Trail"
      eyebrow="Compliance record"
      actions={
        <span
          title="Audit entries are immutable — they are never edited or deleted."
          className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-muted"
        >
          <Lock size={11} /> Read-only
        </span>
      }
    >
      {!canViewAuditTrail ? (
        <EmptyState
          icon="🔒"
          title="Access restricted"
          description="You don't have permission to view this ticket's audit trail."
        />
      ) : isLoading && entries.length === 0 ? (
        <SkeletonRows rows={3} />
      ) : entries.length === 0 ? (
        <EmptyState
          icon="🔒"
          title="No audit events yet"
          description="Ticket changes will appear here permanently once they happen."
        />
      ) : (
        <ol className="flex flex-col gap-3">
          {entries.map((entry) => {
            const meta = auditMetaFor(entry.event_type);
            const fields = diffFields(entry.old_values, entry.new_values);

            return (
              <li
                key={entry.audit_id}
                className="rounded-md2 border border-border bg-canvas/60 p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{meta.icon}</span>
                    <Badge tone={meta.tone}>{meta.label}</Badge>
                  </div>
                  <p className="text-[10px] font-medium text-muted">
                    {formatDateTime(entry.created_at)}
                  </p>
                </div>

                <p className="mt-1.5 text-[11px] text-muted">
                  By <span className="font-medium text-slate-700">{entry.actor_name}</span>
                  <span className="ml-1 text-muted">· {ACTOR_ROLE_LABEL[entry.actor_role]}</span>
                  {entry.impersonator_name && (
                    <span className="ml-1 text-warning">
                      · Impersonated by {entry.impersonator_name} (Super Admin)
                    </span>
                  )}
                </p>

                {fields.length > 0 && (
                  <dl className="mt-2 flex flex-col gap-1">
                    {fields.map((field) => (
                      <div key={field.key} className="flex items-baseline gap-1.5 text-[11px]">
                        <dt className="flex-none font-medium text-slate-600">
                          {humanizeFieldKey(field.key)}:
                        </dt>
                        <dd className="truncate text-muted">
                          {field.from !== null && field.from !== undefined ? (
                            <>
                              {formatFieldValue(field.from)}
                              <span className="mx-1">→</span>
                            </>
                          ) : null}
                          <span className="font-medium text-slate-700">
                            {formatFieldValue(field.to)}
                          </span>
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
