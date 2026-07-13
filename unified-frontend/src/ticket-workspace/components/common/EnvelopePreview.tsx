interface EnvelopePreviewProps {
  senderName: string;
  viaEmail?: string | null;
  toEmail?: string | null;
  subject?: string;
}

function subjectAsReply(subject: string | undefined): string {
  if (!subject) return "this thread";
  return subject.trim().toLowerCase().startsWith("re:") ? subject : `Re: ${subject}`;
}

/**
 * "Sending as X via Y to Z, CC Account Manager, threads as Re: subject"
 * — shared between TicketComposer (ticket-level reply) and
 * EmailDetails (Mail-inbox reply), which both build a reply through
 * the same envelope shape (see app/services/email_envelope.py). Pure
 * preview only — the backend builds the real envelope independently.
 */
export function EnvelopePreview({ senderName, viaEmail, toEmail, subject }: EnvelopePreviewProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-md2 bg-canvas px-3 py-2 text-[10.5px] text-muted">
      <span>Sending as</span>
      <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-medium text-slate-700">
        {senderName}
        {viaEmail ? ` · via ${viaEmail}` : ""}
      </span>
      {toEmail && (
        <>
          <span>to</span>
          <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-medium text-slate-700">
            {toEmail}
          </span>
        </>
      )}
      <span className="ml-auto">threads as {subjectAsReply(subject)}</span>
    </div>
  );
}
