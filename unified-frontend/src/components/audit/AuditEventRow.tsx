import { Badge } from "@tw/components/common/Badge";
import { formatFieldValue } from "@tw/lib/auditLogMeta";
import { formatDate } from "@/lib/utils";
import type { UnifiedAuditEvent } from "@/components/audit/auditEvent.types";

interface AuditEventRowProps {
  event: UnifiedAuditEvent;
  onClick: (event: UnifiedAuditEvent) => void;
}

/**
 * The one, shared presentation of a single audit event — used by both
 * the ticket-scoped Audit Log (AuditLogPage.tsx) and the RBAC-native
 * Centralized Audit Log (CentralizedAuditLogPanel.tsx). Neither page
 * owns its own row JSX anymore; each only normalizes its own API
 * response into a `UnifiedAuditEvent` (see normalizeAuditEvent.ts) and
 * renders it through this component, so the two domains can never
 * visually drift apart again.
 *
 * Structure (fixed, domain-agnostic):
 *   [icon] [action badge] [entity text]        [timestamp]
 *          [field summary line]                [actor · role]
 *                                               [impersonation note]
 *
 * Uses only tokens that resolve identically whether or not an ancestor
 * carries `.tm-scope` (bg-canvas/bg-surface/rounded-md2/border-border/
 * text-muted-foreground are defined with the same values at :root and
 * inside `.tm-scope` — see globals.css) so this renders pixel-for-pixel
 * the same on the ticket workspace page and on the plain `/audit-logs`
 * page.
 */
export function AuditEventRow({ event, onClick }: AuditEventRowProps) {
  const fieldSummary = event.fields
    .map((field) => `${field.label}: ${formatFieldValue(field.to)}`)
    .join(" · ");

  return (
    <li className="flex items-center transition-colors hover:bg-surfaceHover">
      <button
        onClick={() => onClick(event)}
        aria-label={`${event.actionLabel} on ${event.entityLabel}`}
        className="flex min-w-0 flex-1 items-center gap-3.5 px-5 py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40"
      >
        <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
          {event.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <Badge tone={event.tone}>{event.actionLabel}</Badge>
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={event.entityLabel}>
              on <span className="font-medium text-slate-500">{event.entityLabel}</span>
            </span>
            {event.entityMeta && (
              <span
                className="max-w-[140px] flex-none truncate text-xs text-muted-foreground"
                title={event.entityMeta}
              >
                · {event.entityMeta}
              </span>
            )}
          </div>
          {fieldSummary && (
            <p className="mt-1 truncate text-[13px] text-slate-600" title={fieldSummary}>
              {fieldSummary}
            </p>
          )}
        </div>
        <div className="flex-none text-right">
          <p className="text-xs font-medium text-slate-600">{formatDate(event.timestamp)}</p>
          <p
            className="mt-0.5 max-w-[220px] truncate text-[11px] text-muted-foreground"
            title={
              event.impersonatorName
                ? `${event.actorName}${event.actorRole ? ` · ${event.actorRole}` : ""} · Impersonated by ${event.impersonatorName} (Super Admin)`
                : `${event.actorName}${event.actorRole ? ` · ${event.actorRole}` : ""}`
            }
          >
            {event.actorName}
            {event.actorRole && <span className="text-muted-foreground/70"> · {event.actorRole}</span>}
          </p>
          {event.impersonatorName && (
            <p className="mt-0.5 max-w-[220px] truncate text-[11px] text-warning">
              Impersonated by {event.impersonatorName} (Super Admin)
            </p>
          )}
        </div>
      </button>
    </li>
  );
}
