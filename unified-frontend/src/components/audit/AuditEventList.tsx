import type { ReactNode } from "react";

import { WorkflowLoader } from "@/components/common/WorkflowLoader";
import { AuditEventRow } from "@/components/audit/AuditEventRow";
import type { UnifiedAuditEvent } from "@/components/audit/auditEvent.types";

interface AuditEventListProps {
  events: UnifiedAuditEvent[];
  isLoading: boolean;
  onEventClick: (event: UnifiedAuditEvent) => void;
  emptyIcon?: string;
  emptyTitle: string;
  emptyDescription: string;
  // Optional pagination/summary bar rendered inside the same card,
  // below the row list, separated by a top border — pagination
  // mechanics are allowed to differ per domain (server-paginated
  // Previous/Next for the ticket view, a client-paginated table for
  // the centralized view), so this is a plain slot rather than a
  // shared pagination implementation.
  footer?: ReactNode;
}

/**
 * The shared list container both Audit Log views render their events
 * through — same card chrome (rounded-md2/border/shadow), same
 * divide-y row separators, same loading/empty treatment — so that
 * surrounding "card" looks identical regardless of which page mounts
 * it. Each row is rendered via the one shared AuditEventRow; this
 * component owns none of the per-event presentation itself.
 */
export function AuditEventList({
  events,
  isLoading,
  onEventClick,
  emptyIcon = "🔒",
  emptyTitle,
  emptyDescription,
  footer,
}: AuditEventListProps) {
  return (
    <div className="rounded-md2 border border-border bg-surface shadow-xs">
      {isLoading && events.length === 0 ? (
        <WorkflowLoader loading size={56} className="min-h-[400px]" />
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-canvas text-2xl">
            {emptyIcon}
          </div>
          <div className="flex flex-col gap-1">
            <p className="text-sm font-semibold text-slate-700">{emptyTitle}</p>
            <p className="max-w-xs text-xs leading-relaxed text-muted-foreground">{emptyDescription}</p>
          </div>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-border">
            {events.map((event) => (
              <AuditEventRow key={event.id} event={event} onClick={onEventClick} />
            ))}
          </ul>
          {footer && <div className="border-t border-border px-5 py-3 text-xs text-muted-foreground">{footer}</div>}
        </>
      )}
    </div>
  );
}
