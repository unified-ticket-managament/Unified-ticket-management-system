import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { TicketActions } from "@tw/components/ticket/TicketActions";
import { shortId } from "@tw/lib/format";
import type { TicketResponse } from "@tw/types";

interface TicketHeaderProps {
  ticket: TicketResponse;
  onActionComplete: () => void;
}

export function TicketHeader({ ticket, onActionComplete }: TicketHeaderProps) {
  const navigate = useNavigate();

  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <p className="font-mono text-[11px] font-semibold tracking-wide text-accent">
          TKT-{shortId(ticket.ticket_id, 8)}
        </p>
        <h2 className="mt-1 text-2xl font-bold leading-tight text-slate-900">
          {ticket.title}
        </h2>
      </div>

      <TicketActions onActionComplete={onActionComplete} />
    </div>
  );
}
