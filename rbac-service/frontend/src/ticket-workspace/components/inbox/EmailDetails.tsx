import { Mail, Ticket as TicketIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@tw/components/common/Badge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

export function EmailDetails() {
  const { selectedEmail, activeTicket } = useWorkflowContext();

  if (!selectedEmail) {
    return (
      <div className="flex h-full items-center justify-center rounded-md2 border border-border bg-surface shadow-xs">
        <EmptyState
          icon="✉️"
          title="No email selected"
          description="Open an email from the list to see its full content here."
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-accent/10 text-accent">
            <Mail size={16} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[13px] font-semibold text-slate-900">
              {selectedEmail.from_email}
            </p>
            <p className="text-[11px] text-muted">{selectedEmail.client_name}</p>
          </div>
        </div>
        <Badge tone="warning" dot>
          {selectedEmail.status}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-3 border-b border-border bg-canvas/50 px-5 py-3 text-[11px]">
        <div>
          <p className="text-muted">To</p>
          <p className="mt-0.5 font-medium text-slate-700">{selectedEmail.agent_name}</p>
        </div>
        <div>
          <p className="text-muted">Received</p>
          <p className="mt-0.5 font-medium text-slate-700">
            {new Date(selectedEmail.received_at).toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-muted">Source</p>
          <p className="mt-0.5 font-medium text-slate-700">Email</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-5">
        <p className="mb-3 text-[15px] font-semibold text-slate-900">
          {selectedEmail.subject}
        </p>
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
          {selectedEmail.body}
        </p>

        {selectedEmail.attachments && selectedEmail.attachments.length > 0 && (
          <div className="mt-5 border-t border-border pt-4">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
              Attachments
            </p>
            <AttachmentList attachments={selectedEmail.attachments} />
          </div>
        )}
      </div>

      {activeTicket && (
        <Link
          to={`/tickets/${activeTicket.ticket_id}`}
          className="flex items-center gap-2 border-t border-border bg-accent/5 px-5 py-3 text-xs font-medium text-accent transition-colors hover:bg-accent/10"
        >
          <TicketIcon size={13} />
          Linked to ticket{" "}
          <span className="font-mono">{activeTicket.ticket_id.slice(0, 8)}…</span>
        </Link>
      )}
    </div>
  );
}
