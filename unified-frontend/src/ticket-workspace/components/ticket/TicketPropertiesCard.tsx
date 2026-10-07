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
// specced (Client/Status/Priority/Created By/Assigned To/Assigned By,
// then Category/Created On/Latest Updated/Version) — every value
// sourced directly from the existing ticket response, nothing
// hardcoded.
export function TicketPropertiesCard({ ticket }: { ticket: TicketResponse }) {
  // Multi-assignment: agent_id/ticket_type stay the PRIMARY assignee/
  // category; the full lists live in the Assignments card below.
  const secondaryAssignees = (ticket.assignees ?? []).filter((a) => !a.is_primary);
  const otherAssignees = secondaryAssignees.length;
  const extraCategories = (ticket.categories ?? []).filter((c) => !c.is_primary);
  const otherCategories = extraCategories.length;
  return (
    <Card title="Properties">
      <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
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
          {otherAssignees > 0 && ticket.agent_id && (
            <span className="ml-1 text-[10px] font-normal uppercase text-muted">(Primary)</span>
          )}
          {secondaryAssignees.map((a) => (
            <div key={a.assignment_id} className="truncate text-[12px] font-normal text-slate-700">
              {a.user_name ?? shortId(a.user_id)}
            </div>
          ))}
        </Field>
        <Field label="Assigned By">
          {ticket.assigned_by
            ? ticket.assigned_by_name ?? shortId(ticket.assigned_by)
            : "—"}
        </Field>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-4 border-t border-border pt-4 sm:grid-cols-4">
        <Field label={otherCategories > 0 ? "Categories" : "Category"}>
          {ticket.ticket_type}
          {extraCategories.map((c) => (
            <div key={c.category_id} className="truncate text-[12px] font-normal text-slate-700">
              {c.category_name}
            </div>
          ))}
        </Field>
        <Field label="Created On">{formatDateTime(ticket.created_at)}</Field>
        <Field label="Latest Updated">{formatDateTime(ticket.updated_at)}</Field>
        <Field label="Version">{ticket.version}</Field>
      </div>
    </Card>
  );
}
