import { useEffect } from "react";
import { X } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { formatFieldValue } from "@tw/lib/auditLogMeta";
import { formatDate } from "@/lib/utils";
import type { UnifiedAuditEvent } from "@/components/audit/auditEvent.types";

interface AuditEventDetailsDrawerProps {
  open: boolean;
  event: UnifiedAuditEvent | null;
  onClose: () => void;
}

/**
 * The one details side-panel both Audit Log views open a row into —
 * replaces the ticket workspace's former AuditLogDetailsDrawer and the
 * Centralized Audit Log's former CentralizedAuditLogDetailsDrawer,
 * which duplicated (and had started to visually drift from) this exact
 * layout. Domain-specific facts (a ticket's related-ticket title/"View
 * Ticket" button; a centralized row's IP address/email/status) are
 * supplied via the event's own `metadata`/`primaryAction` — the drawer
 * itself has no domain knowledge, so a field simply doesn't render
 * when the producing domain has nothing to put there (see
 * normalizeAuditEvent.ts), rather than the drawer growing a different
 * layout per domain.
 *
 * Same portability note as AuditEventRow/AuditEventList: only tokens
 * that resolve identically inside `.tm-scope` and on the plain
 * `/audit-logs` page are used here.
 */
export function AuditEventDetailsDrawer({ open, event, onClose }: AuditEventDetailsDrawerProps) {
  // Closes only via the X button below — no Escape-key listener, and
  // the overlay below has no onClick — matching every other drawer in
  // this app's own deliberate "no outside-click/Escape dismiss"
  // convention (see unified-frontend/CLAUDE.md).
  useEffect(() => {
    if (!open) return;

    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <div
        aria-hidden={!open}
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-300 motion-reduce:transition-none ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Audit event details"
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-surface shadow-2xl transition-transform duration-300 ease-out motion-reduce:transition-none ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {event && (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                  {event.icon}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[14px] font-semibold text-slate-900">{event.actionLabel}</p>
                  <p className="text-[11px] text-muted-foreground">Audit Event Details</p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close details drawer"
                className="flex h-8 w-8 flex-none items-center justify-center rounded-md2 text-muted-foreground transition-colors hover:bg-surfaceHover hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={event.tone}>{event.actionLabel}</Badge>
                {event.entityTypeLabel && <Badge tone="default">{event.entityTypeLabel}</Badge>}
              </div>

              {event.impersonatorName && (
                <p className="mt-3 text-[13px] text-warning">
                  Impersonated by {event.impersonatorName} (Super Admin)
                </p>
              )}

              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Audit ID</dt>
                  <dd className="mt-0.5 truncate font-mono text-[11px] text-slate-800">{event.id}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Entity</dt>
                  <dd className="mt-0.5 truncate font-medium text-slate-800" title={event.entityLabel}>
                    {event.entityLabel}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Actor</dt>
                  <dd
                    className="mt-0.5 truncate font-medium text-slate-800"
                    title={event.actorRole ? `${event.actorName} · ${event.actorRole}` : event.actorName}
                  >
                    {event.actorName}
                    {event.actorRole && <span className="ml-1 text-muted-foreground">· {event.actorRole}</span>}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-muted-foreground">Timestamp</dt>
                  <dd className="mt-0.5 truncate font-medium text-slate-800">{formatDate(event.timestamp)}</dd>
                </div>
                {(event.metadata ?? []).map((item) => (
                  <div key={item.label} className="min-w-0">
                    <dt className="text-muted-foreground">{item.label}</dt>
                    <dd
                      className={`mt-0.5 truncate font-medium text-slate-800 ${item.mono ? "font-mono text-[11px]" : ""}`}
                      title={item.value}
                    >
                      {item.value}
                    </dd>
                  </div>
                ))}
              </dl>

              <div className="mt-5 border-t border-border pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Changed Fields
                </p>
                {event.fields.length === 0 ? (
                  <p className="mt-2 text-[13px] text-muted-foreground">
                    No before/after values recorded for this event.
                  </p>
                ) : (
                  <dl className="mt-2 flex flex-col gap-2.5">
                    {event.fields.map((field) => (
                      <div key={field.key} className="min-w-0 text-xs">
                        <dt className="text-muted-foreground">{field.label}</dt>
                        <dd className="mt-0.5 break-words font-medium text-slate-800">
                          {field.from !== null && field.from !== undefined ? (
                            <>
                              <span className="text-muted-foreground">{formatFieldValue(field.from)}</span>
                              <span className="mx-1.5 text-muted-foreground">→</span>
                            </>
                          ) : null}
                          {formatFieldValue(field.to)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            </div>

            {event.primaryAction && (
              <div className="border-t border-border px-5 py-4">
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  icon={event.primaryAction.icon}
                  onClick={event.primaryAction.onClick}
                >
                  {event.primaryAction.label}
                </Button>
              </div>
            )}
          </>
        )}
      </aside>
    </>
  );
}
