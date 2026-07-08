import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, X } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { shortId, formatDateTime } from "@/lib/format";
import { priorityTone, statusTone } from "@/lib/ticketTone";
import { useApiAction } from "@/hooks/useApiAction";
import { addRelatedTicket, listTickets, removeRelatedTicket } from "@/api/ticket";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { TicketResponse } from "@/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="text-xs font-medium text-slate-800">{children}</dd>
    </div>
  );
}

interface TicketDetailsProps {
  // Refetches the ticket so `related_tickets` reflects a link/unlink
  // immediately — the same `refreshAll` TicketDetailPage already
  // passes into TicketActions for every other mutating action.
  onRelatedChanged: () => void;
}

export function TicketDetails({ onRelatedChanged }: TicketDetailsProps) {
  const { activeTicket } = useWorkflowContext();
  const [isPicking, setIsPicking] = useState(false);
  const [allTickets, setAllTickets] = useState<TicketResponse[]>([]);
  const [selectedTicketId, setSelectedTicketId] = useState("");

  const { run: runAdd, isLoading: isAdding } = useApiAction(addRelatedTicket, {
    successMessage: "Tickets linked.",
  });
  const { run: runRemove } = useApiAction(removeRelatedTicket);

  useEffect(() => {
    if (!isPicking) return;
    listTickets()
      .then(setAllTickets)
      .catch(() => {
        // Picker just stays empty — the useApiAction pattern isn't
        // used here since this is a background convenience fetch,
        // not a user-initiated action that needs its own toast.
      });
  }, [isPicking]);

  if (!activeTicket) return null;

  const relatedIds = new Set(activeTicket.related_tickets.map((related) => related.ticket_id));
  const pickableTickets = allTickets.filter(
    (t) => t.ticket_id !== activeTicket.ticket_id && !relatedIds.has(t.ticket_id)
  );

  async function handleLink() {
    if (!activeTicket || !selectedTicketId) return;
    const result = await runAdd(activeTicket.ticket_id, selectedTicketId);
    if (result) {
      setSelectedTicketId("");
      setIsPicking(false);
      onRelatedChanged();
    }
  }

  async function handleUnlink(relatedTicketId: string) {
    if (!activeTicket) return;
    const result = await runRemove(activeTicket.ticket_id, relatedTicketId);
    if (result) onRelatedChanged();
  }

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

      <div className="mt-2 border-t border-border pt-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Related Tickets
          </p>
          <button
            onClick={() => setIsPicking((prev) => !prev)}
            title="Link a related ticket"
            className="rounded p-0.5 text-muted/70 hover:bg-surfaceHover hover:text-slate-900"
          >
            {isPicking ? <X size={13} /> : <Plus size={13} />}
          </button>
        </div>

        {isPicking && (
          <div className="mb-2 flex items-center gap-1.5">
            <select
              value={selectedTicketId}
              onChange={(e) => setSelectedTicketId(e.target.value)}
              className="w-full flex-1 cursor-pointer rounded-md2 border border-border bg-white px-2 py-1.5 text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-accent/40"
            >
              <option value="">Select a ticket…</option>
              {pickableTickets.map((t) => (
                <option key={t.ticket_id} value={t.ticket_id}>
                  {t.title} ({t.ticket_type} · {t.current_status})
                </option>
              ))}
            </select>
            <Button
              size="sm"
              variant="primary"
              isLoading={isAdding}
              disabled={!selectedTicketId}
              onClick={handleLink}
            >
              Link
            </Button>
          </div>
        )}

        {activeTicket.related_tickets.length === 0 ? (
          <p className="text-[12px] text-muted/60">No related tickets.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {activeTicket.related_tickets.map((related) => (
              <li
                key={related.ticket_id}
                className="group flex items-center justify-between gap-2 rounded-md2 border border-border px-2.5 py-1.5"
              >
                <Link
                  to={`/tickets/${related.ticket_id}`}
                  className="min-w-0 flex-1 truncate text-[12px] font-medium text-accent hover:underline"
                >
                  {related.title}
                </Link>
                <Badge tone={statusTone[related.current_status]} dot>
                  {related.current_status}
                </Badge>
                <button
                  onClick={() => handleUnlink(related.ticket_id)}
                  title="Unlink"
                  className="flex-none rounded p-0.5 text-muted/50 opacity-0 hover:text-danger group-hover:opacity-100"
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
