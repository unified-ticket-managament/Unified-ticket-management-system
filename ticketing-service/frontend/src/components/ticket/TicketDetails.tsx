import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { shortId, formatDateTime } from "@/lib/format";
import { priorityTone, statusTone } from "@/lib/ticketTone";
import { useWorkflowContext } from "@/context/WorkflowContext";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-xs font-medium text-slate-800">{children}</dd>
    </div>
  );
}

export function TicketDetails() {
  const { activeTicket } = useWorkflowContext();
  if (!activeTicket) return null;

  return (
    // One card instead of two separate ones — cuts a whole extra
    // header/border/shadow out of the right column so Actions and
    // the Audit Trail sit closer to the fold instead of needing a
    // scroll past two thin, mostly-empty-looking boxes.
    <Card title="Ticket Properties" eyebrow="Overview">
      <dl className="flex flex-col divide-y divide-border">
        <Row label="Status">
          <Badge tone={statusTone[activeTicket.current_status]} dot>
            {activeTicket.current_status}
          </Badge>
        </Row>
        <Row label="Priority">
          <Badge tone={priorityTone[activeTicket.current_priority]}>
            {activeTicket.current_priority}
          </Badge>
        </Row>
        <Row label="Category">{activeTicket.ticket_type}</Row>
        <Row label="Version">{activeTicket.version}</Row>
        <Row label="Client">
          {activeTicket.client_company_name ??
            activeTicket.client_name ??
            (activeTicket.client_id ? shortId(activeTicket.client_id) : "—")}
        </Row>
        <Row label="Assigned Agent">
          {activeTicket.agent_id
            ? activeTicket.agent_name ?? shortId(activeTicket.agent_id)
            : "Unassigned"}
        </Row>
        <Row label="Updated">{formatDateTime(activeTicket.updated_at)}</Row>
        {activeTicket.closed_at && (
          <Row label="Resolved At">{formatDateTime(activeTicket.closed_at)}</Row>
        )}
      </dl>
    </Card>
  );
}
