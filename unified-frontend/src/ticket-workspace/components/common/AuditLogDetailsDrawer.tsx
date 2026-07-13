import { useEffect } from "react";
import { X, Ticket as TicketIcon } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { auditMetaFor, diffFields, formatFieldValue, humanizeFieldKey } from "@tw/lib/auditLogMeta";
import { shortId, formatDateTime } from "@tw/lib/format";
import type { ActorRole, AuditEntityType, AuditEventType } from "@tw/types";

// Fields the drawer needs — matches the `AuditRow` shape AuditLogPage.tsx
// already builds from `getTicketAuditLogs`, so no extra fetch is needed
// to show this summary.
export interface AuditLogDrawerRow {
  auditId: string;
  createdAt: string;
  entityType: AuditEntityType;
  eventType: AuditEventType;
  actorName: string;
  actorRole: ActorRole;
  ticketId: string;
  ticketTitle: string;
  oldValues: Record<string, unknown> | null;
  newValues: Record<string, unknown> | null;
}

interface AuditLogDetailsDrawerProps {
  open: boolean;
  row: AuditLogDrawerRow | null;
  onClose: () => void;
  onViewTicket: (ticketId: string) => void;
}

const ACTOR_ROLE_LABEL: Record<ActorRole, string> = {
  AGENT: "Agent",
  CLIENT: "Client",
  SYSTEM: "System",
};

export function AuditLogDetailsDrawer({
  open,
  row,
  onClose,
  onViewTicket,
}: AuditLogDetailsDrawerProps) {
  // Closes only via the X button below — no Escape-key listener, and
  // the overlay below has no onClick — so outside-click/Escape never
  // close this drawer.
  useEffect(() => {
    if (!open) return;

    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const meta = row ? auditMetaFor(row.eventType) : null;
  const fields = row ? diffFields(row.oldValues, row.newValues) : [];

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
        {row && meta && (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                  {meta.icon}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[14px] font-semibold text-slate-900">{meta.label}</p>
                  <p className="text-[11px] text-muted">Audit Event Details</p>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="Close details drawer"
                className="flex h-8 w-8 flex-none items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={meta.tone}>{meta.label}</Badge>
                <Badge tone="default">{row.entityType}</Badge>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                <div>
                  <dt className="text-muted">Audit ID</dt>
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-800">
                    {shortId(row.auditId, 12)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Related Ticket</dt>
                  <dd className="mt-0.5 truncate font-medium text-slate-800">{row.ticketTitle}</dd>
                </div>
                <div>
                  <dt className="text-muted">Actor</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">
                    {row.actorName}
                    <span className="ml-1 text-muted">· {ACTOR_ROLE_LABEL[row.actorRole]}</span>
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Timestamp</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">
                    {formatDateTime(row.createdAt)}
                  </dd>
                </div>
              </dl>

              <div className="mt-5 border-t border-border pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Changed Fields
                </p>
                {fields.length === 0 ? (
                  <p className="mt-2 text-[13px] text-muted">
                    No before/after values recorded for this event.
                  </p>
                ) : (
                  <dl className="mt-2 flex flex-col gap-2.5">
                    {fields.map((field) => (
                      <div key={field.key} className="text-xs">
                        <dt className="text-muted">{humanizeFieldKey(field.key)}</dt>
                        <dd className="mt-0.5 font-medium text-slate-800">
                          {field.from !== null && field.from !== undefined ? (
                            <>
                              <span className="text-muted">{formatFieldValue(field.from)}</span>
                              <span className="mx-1.5 text-muted">→</span>
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

            <div className="border-t border-border px-5 py-4">
              <Button
                variant="primary"
                size="sm"
                className="w-full"
                icon={<TicketIcon size={14} />}
                onClick={() => onViewTicket(row.ticketId)}
              >
                View Ticket
              </Button>
            </div>
          </>
        )}
      </aside>
    </>
  );
}
