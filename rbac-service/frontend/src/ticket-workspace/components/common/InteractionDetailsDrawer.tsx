import { useEffect } from "react";
import { X, Ticket as TicketIcon } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import { metaFor, summarize } from "@tw/lib/interactionMeta";
import { shortId, formatDateTime } from "@tw/lib/format";
import type {
  AttachmentMeta,
  InteractionDirection,
  InteractionResponse,
  InteractionStatus,
} from "@tw/types";

// Fields the drawer needs. Any row-like object with at least these
// fields can be passed in — the page owns fetching/shaping the data,
// this component only renders it.
export interface InteractionDrawerRow {
  id: string;
  createdAt: string;
  type: string;
  direction: InteractionDirection;
  status: InteractionStatus;
  ticketId: string | null;
  ticketTitle: string | null;
  clientName: string | null;
  agent: string;
  summaryText: string;
  // Full backend record, when already available (ticket-linked rows
  // fetched via the ticket timeline endpoint already carry it — no
  // extra request needed).
  raw?: InteractionResponse;
}

// Present for pending inbox rows once fetched via the existing
// GET /agents/{agent}/inbox/{interaction_id} endpoint.
export interface InteractionDrawerEmail {
  from_email: string;
  client_name: string;
  agent_name: string;
  subject: string;
  body: string;
  message_id: string | null;
  attachments?: AttachmentMeta[];
}

interface InteractionDetailsDrawerProps {
  open: boolean;
  row: InteractionDrawerRow | null;
  email?: InteractionDrawerEmail | null;
  isLoadingEmail?: boolean;
  onClose: () => void;
  onViewTicket: (ticketId: string) => void;
}

const sourceLabels: Record<string, string> = {
  EMAIL: "Email",
  REPLY: "Email",
  INTERNAL_NOTE: "Internal System",
  STATUS_CHANGE: "Internal System",
  PRIORITY_CHANGE: "Internal System",
  AGENT_TRANSFER: "Internal System",
  ATTACHMENT: "File Upload",
};

const HIDDEN_PAYLOAD_KEYS = new Set([
  "client_name",
  "agent_name",
  "from_agent_name",
  "to_agent_name",
  "subject",
  "body",
  "message",
  "note",
  "filename",
]);

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bId\b/g, "ID");
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

interface ResolvedFields {
  from: string | null;
  to: string | null;
  subject: string | null;
  message: string | null;
  attachments: AttachmentMeta[];
  extra: Array<[string, unknown]>;
}

// From/To/Subject only mean something for a subset of interaction
// types — email-like ones with a real sender/recipient/subject.
// Everything else (notes, attachments, status/priority/transfer,
// resolve) has no subject and no "sent to" concept, so those fields
// are left `null` here and simply not rendered, instead of always
// showing a blank "—".
function resolveFromToSubject(
  row: InteractionDrawerRow,
  payload: Record<string, unknown>
): { from: string | null; to: string | null; subject: string | null } {
  switch (row.type) {
    case "EMAIL":
      return {
        from: (payload.client_name as string) ?? (payload.from_email as string) ?? null,
        to: (payload.agent_name as string) ?? null,
        subject: (payload.subject as string) ?? null,
      };
    case "REPLY":
      // Agent replying to the client — reversed from an inbound EMAIL.
      return { from: row.agent || null, to: row.clientName, subject: null };
    case "INTERNAL_NOTE":
    case "ATTACHMENT":
      // Authored/uploaded by the agent, not sent to anyone.
      return { from: row.agent || null, to: null, subject: null };
    case "AGENT_TRANSFER":
      return {
        from: (payload.from_agent_name as string) ?? "Unassigned",
        to: (payload.to_agent_name as string) ?? null,
        subject: null,
      };
    default:
      // STATUS_CHANGE, PRIORITY_CHANGE, RESOLVED, etc. — their
      // from/to payload fields are status/priority values, not
      // people, and the summary line already covers the transition.
      return { from: null, to: null, subject: null };
  }
}

function resolveFields(
  row: InteractionDrawerRow,
  email?: InteractionDrawerEmail | null
): ResolvedFields {
  // Pending inbox row — only the list summary is known until the
  // full email is fetched on demand.
  if (!row.ticketId) {
    if (!email) {
      return { from: null, to: null, subject: row.summaryText, message: null, attachments: [], extra: [] };
    }
    return {
      from: email.client_name ?? email.from_email,
      to: email.agent_name,
      subject: email.subject,
      message: email.body,
      attachments: email.attachments ?? [],
      extra: [["from_email", email.from_email], ["message_id", email.message_id]],
    };
  }

  const payload = row.raw?.payload ?? {};
  const message =
    (payload.body ?? payload.message ?? payload.note) as string | undefined ??
    (row.raw ? summarize(row.raw) : row.summaryText);
  const attachments = row.raw?.attachments ?? [];
  const extra = Object.entries(payload).filter(
    ([key, value]) => !HIDDEN_PAYLOAD_KEYS.has(key) && value !== null && value !== undefined
  );

  return {
    ...resolveFromToSubject(row, payload),
    message: message ?? null,
    attachments,
    extra,
  };
}

export function InteractionDetailsDrawer({
  open,
  row,
  email,
  isLoadingEmail,
  onClose,
  onViewTicket,
}: InteractionDetailsDrawerProps) {
  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  const meta = row ? metaFor(row.type) : null;
  const fields = row ? resolveFields(row, email) : null;

  return (
    <>
      <div
        aria-hidden={!open}
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-300 motion-reduce:transition-none ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Interaction details"
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-surface shadow-2xl transition-transform duration-300 ease-out motion-reduce:transition-none ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {row && meta && fields && (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
              <div className="flex items-center gap-3 min-w-0">
                <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-border bg-canvas text-base">
                  {meta.icon}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-[14px] font-semibold text-slate-900">{meta.label}</p>
                  <p className="text-[11px] text-muted">Interaction Details</p>
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
                <Badge tone={meta.tone}>{row.direction}</Badge>
                <Badge tone="default">{row.status}</Badge>
              </div>

              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                <div>
                  <dt className="text-muted">Interaction ID</dt>
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-800">{shortId(row.id, 12)}</dd>
                </div>
                <div>
                  <dt className="text-muted">Related Ticket</dt>
                  <dd className="mt-0.5 font-mono text-[11px] text-slate-800">
                    {row.ticketId ? shortId(row.ticketId, 12) : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Source</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">
                    {sourceLabels[row.type] ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted">Performed By</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">{row.agent || "—"}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-muted">Created / Received</dt>
                  <dd className="mt-0.5 font-medium text-slate-800">{formatDateTime(row.createdAt)}</dd>
                </div>
              </dl>

              {(fields.from || fields.to || fields.subject) && (
                <div className="mt-5 border-t border-border pt-4">
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                    {fields.from && (
                      <div>
                        <dt className="text-muted">From</dt>
                        <dd className="mt-0.5 font-medium text-slate-800">{fields.from}</dd>
                      </div>
                    )}
                    {fields.to && (
                      <div>
                        <dt className="text-muted">To</dt>
                        <dd className="mt-0.5 font-medium text-slate-800">{fields.to}</dd>
                      </div>
                    )}
                    {fields.subject && (
                      <div className="col-span-2">
                        <dt className="text-muted">Subject</dt>
                        <dd className="mt-0.5 font-medium text-slate-800">{fields.subject}</dd>
                      </div>
                    )}
                  </dl>
                </div>
              )}

              <div className="mt-5 border-t border-border pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                  Message Content
                </p>
                {isLoadingEmail ? (
                  <p className="mt-2 text-[13px] text-muted">Loading…</p>
                ) : (
                  <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                    {fields.message ?? "—"}
                  </p>
                )}
              </div>

              {fields.attachments.length > 0 && (
                <div className="mt-5 border-t border-border pt-4">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Attachments
                  </p>
                  <AttachmentList attachments={fields.attachments} className="mt-2" />
                </div>
              )}

              {fields.extra.length > 0 && (
                <div className="mt-5 border-t border-border pt-4">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
                    Additional Details
                  </p>
                  <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
                    {fields.extra.map(([key, value]) => (
                      <div key={key}>
                        <dt className="text-muted">{humanizeKey(key)}</dt>
                        <dd className="mt-0.5 break-all font-medium text-slate-800">
                          {displayValue(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>

            <div className="border-t border-border px-5 py-4">
              {row.ticketId ? (
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  icon={<TicketIcon size={14} />}
                  onClick={() => onViewTicket(row.ticketId!)}
                >
                  View Ticket
                </Button>
              ) : (
                <p className="text-center text-[11px] text-muted">
                  Not yet attached to a ticket.
                </p>
              )}
            </div>
          </>
        )}
      </aside>
    </>
  );
}
