import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, X } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { useApiAction } from "@tw/hooks/useApiAction";
import { addRelatedTicket, listTickets, removeRelatedTicket } from "@tw/api/ticket";
import { statusTone } from "@tw/lib/ticketTone";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { TicketResponse } from "@tw/types";

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
    // Related Tickets used to share a card with the Status/Priority/
    // Category/etc. property list — those now live in the dedicated,
    // full-width TicketPropertiesCard instead (see TicketDetailPage),
    // so this component keeps only the Related Tickets management UI.
    <Card
      title="Related Tickets"
      actions={
        <button
          onClick={() => setIsPicking((prev) => !prev)}
          title="Link a related ticket"
          className="rounded p-0.5 text-muted/70 hover:bg-surfaceHover hover:text-slate-900"
        >
          {isPicking ? <X size={13} /> : <Plus size={13} />}
        </button>
      }
    >
      <div>
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
