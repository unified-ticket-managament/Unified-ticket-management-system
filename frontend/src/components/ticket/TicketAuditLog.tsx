import { useEffect, useRef, useState } from "react";
import { Lock } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { getTicketAuditLogs } from "@/api/auditLog";
import { auditMetaFor, diffFields, formatFieldValue, humanizeFieldKey } from "@/lib/auditLogMeta";
import { formatDateTime } from "@/lib/format";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { ActorRole } from "@/types";

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
}

export function TicketAuditLog({ refreshToken }: TicketAuditLogProps) {
  const { activeTicket, agentName } = useWorkflowContext();
  const ticketId = activeTicket?.ticket_id;

  const [entries, setEntries] = useState<
    Awaited<ReturnType<typeof getTicketAuditLogs>>
  >([]);
  const [isLoading, setIsLoading] = useState(true);
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!ticketId) return;

    let cancelled = false;
    const thisRequestId = ++requestIdRef.current;

    async function load(showLoading: boolean) {
      if (showLoading) setIsLoading(true);
      try {
        const data = await getTicketAuditLogs(ticketId!, agentName);
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
    const interval = window.setInterval(() => load(false), POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticketId, agentName, refreshToken]);

  return (
    <Card
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
      {isLoading && entries.length === 0 ? (
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
