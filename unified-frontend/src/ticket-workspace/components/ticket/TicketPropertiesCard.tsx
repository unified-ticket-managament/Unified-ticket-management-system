import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { shortId, formatDateTime } from "@tw/lib/format";
import { priorityTone, statusTone } from "@tw/lib/ticketTone";
import type { TicketResponse } from "@tw/types";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</p>
      <div className="mt-1 truncate text-[13px] font-medium text-slate-800">{children}</div>
    </div>
  );
}

// Full-width ticket properties, laid out in two rows exactly as
// specced (Client/Status/Priority/Created By/Assigned To, then
// Category/Created On/Latest Updated/Version) — every value sourced
// directly from the existing ticket response, nothing hardcoded.
export function TicketPropertiesCard({ ticket }: { ticket: TicketResponse }) {
  return (
    <Card title="Properties">
      <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-5">
        <Field label="Client">
          {ticket.client_company_name ??
            ticket.client_name ??
            (ticket.client_id ? shortId(ticket.client_id) : "—")}
        </Field>
        <Field label="Status">
          <Badge tone={statusTone[ticket.current_status]} dot>
            {ticket.current_status}
          </Badge>
        </Field>
        <Field label="Priority">
          <Badge tone={priorityTone[ticket.current_priority]}>{ticket.current_priority}</Badge>
        </Field>
        <Field label="Created By">
          {ticket.created_by ? ticket.created_by_name ?? shortId(ticket.created_by) : "System"}
        </Field>
        <Field label="Assigned To">
          {ticket.agent_id ? ticket.agent_name ?? shortId(ticket.agent_id) : "Unassigned"}
        </Field>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4 border-t border-border pt-4 sm:grid-cols-4">
        <Field label="Category">{ticket.ticket_type}</Field>
        <Field label="Created On">{formatDateTime(ticket.created_at)}</Field>
        <Field label="Latest Updated">{formatDateTime(ticket.updated_at)}</Field>
        <Field label="Version">{ticket.version}</Field>
      </div>
    </Card>
  );
}
