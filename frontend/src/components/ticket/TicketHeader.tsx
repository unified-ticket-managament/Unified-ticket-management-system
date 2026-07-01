import { Badge } from "@/components/common/Badge";
import { shortId, formatDateTime } from "@/lib/format";
import { priorityTone, statusTone } from "@/lib/ticketTone";
import type { TicketResponse } from "@/types";

export function TicketHeader({ ticket }: { ticket: TicketResponse }) {
  return (
    <div className="rounded-md2 border border-border bg-surface p-6 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-semibold tracking-wide text-accent">
            TKT-{shortId(ticket.ticket_id, 8)}
          </p>
          <h2 className="mt-1 text-xl font-bold leading-tight text-slate-900">
            {ticket.title}
          </h2>
        </div>
        <div className="flex flex-none items-center gap-2">
          <Badge tone={statusTone[ticket.current_status]} dot>
            {ticket.current_status}
          </Badge>
          <Badge tone={priorityTone[ticket.current_priority]}>{ticket.current_priority}</Badge>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-5 border-t border-border pt-5 text-xs sm:grid-cols-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Category</p>
          <p className="mt-1 font-medium text-slate-800">{ticket.ticket_type}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Assigned Agent</p>
          <p className="mt-1 font-medium text-slate-800">
            {ticket.agent_id
              ? ticket.agent_name ?? shortId(ticket.agent_id)
              : "Unassigned"}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Client</p>
          <p className="mt-1 font-medium text-slate-800">
            {ticket.client_name ?? shortId(ticket.client_id)}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">Created</p>
          <p className="mt-1 font-medium text-slate-800">
            {formatDateTime(ticket.created_at)}
          </p>
        </div>
      </div>
    </div>
  );
}
