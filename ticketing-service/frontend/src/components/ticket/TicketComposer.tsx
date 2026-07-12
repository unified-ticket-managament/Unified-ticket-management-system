import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { EnvelopePreview } from "@/components/common/EnvelopePreview";
import { SelectInput, TextArea, TextInput } from "@/components/common/FormField";
import { useApiAction } from "@/hooks/useApiAction";
import { listClientContacts } from "@/api/clients";
import { addInternalNote, replyToClient } from "@/api/interaction";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { ClientContact } from "@/types";

export type ComposerMode = "reply" | "note";

interface TicketComposerProps {
  mode: ComposerMode;
  onClose: () => void;
  onSent: () => void;
}

export function TicketComposer({ mode, onClose, onSent }: TicketComposerProps) {
  const { activeTicket, timeline } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [activeMode, setActiveMode] = useState<ComposerMode>(mode);
  const [message, setMessage] = useState("");
  const [noteSubject, setNoteSubject] = useState("");
  const [contacts, setContacts] = useState<ClientContact[]>([]);
  const [selectedTo, setSelectedTo] = useState("");

  const { run: runReply, isLoading: isReplyLoading } = useApiAction(replyToClient, {
    successMessage: "Reply sent to client.",
  });
  const { run: runNote, isLoading: isNoteLoading } = useApiAction(addInternalNote, {
    successMessage: "Internal note added.",
  });

  // Envelope preview — derived from the latest inbound email on this
  // ticket's timeline, so the agent sees exactly where a reply will
  // go before sending it. Trust-building UI, not the source of truth
  // (the backend builds the real envelope independently).
  const latestEmail = useMemo(() => {
    return [...timeline]
      .filter((i) => i.interaction_type === "EMAIL")
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  }, [timeline]);

  const toEmail = latestEmail?.payload.to_email as string | undefined;
  const fromEmail = latestEmail?.payload.from_email as string | undefined;
  const subject = latestEmail?.payload.subject as string | undefined;

  // Every personal address this client has ever emailed the shared
  // inbox from — lets the agent redirect a reply to a different
  // contact at the same client company instead of always the sender
  // of whichever email happens to be most recent.
  useEffect(() => {
    if (!activeTicket?.client_company_id) {
      setContacts([]);
      return;
    }
    listClientContacts(activeTicket.client_company_id)
      .then(setContacts)
      .catch(() => setContacts([]));
  }, [activeTicket?.client_company_id]);

  // Defaults to the latest inbound email's sender whenever the open
  // ticket changes — the agent can still override it below.
  useEffect(() => {
    setSelectedTo(fromEmail ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTicket?.ticket_id]);

  const toOptions = useMemo(() => {
    const seen = new Set<string>();
    const options: ClientContact[] = [];
    for (const contact of [
      ...(fromEmail ? [{ email: fromEmail, name: null }] : []),
      ...contacts,
    ]) {
      if (seen.has(contact.email)) continue;
      seen.add(contact.email);
      options.push(contact);
    }
    return options;
  }, [contacts, fromEmail]);

  if (!activeTicket) return null;

  const isReply = activeMode === "reply";
  const isLoading = isReply ? isReplyLoading : isNoteLoading;

  async function handleSend() {
    if (!activeTicket || !message.trim()) return;
    if (!isReply && !noteSubject.trim()) return;

    const result = isReply
      ? await runReply(activeTicket.ticket_id, { message, to_email: selectedTo || undefined })
      : await runNote(activeTicket.ticket_id, { note: message, subject: noteSubject });

    if (result) {
      setMessage("");
      setNoteSubject("");
      onSent();
    }
  }

  return (
    <Card
      title="Reply"
      eyebrow="Composer"
      actions={
        <button
          onClick={onClose}
          aria-label="Close composer"
          className="flex h-7 w-7 items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-slate-900"
        >
          <X size={15} />
        </button>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex rounded-md2 border border-border p-0.5 text-xs font-semibold">
          <button
            onClick={() => setActiveMode("reply")}
            aria-pressed={isReply}
            className={`flex-1 rounded-[7px] py-1.5 transition-colors ${
              isReply ? "bg-accent/10 text-accent" : "text-muted hover:text-slate-700"
            }`}
          >
            Reply to client
          </button>
          <button
            onClick={() => setActiveMode("note")}
            aria-pressed={!isReply}
            className={`flex-1 rounded-[7px] py-1.5 transition-colors ${
              !isReply ? "bg-warning/10 text-warning" : "text-muted hover:text-slate-700"
            }`}
          >
            Internal note
          </button>
        </div>

        {isReply && (
          <>
            {toOptions.length > 1 && (
              <SelectInput
                label="To"
                value={selectedTo}
                onChange={(e) => setSelectedTo(e.target.value)}
              >
                {toOptions.map((contact) => (
                  <option key={contact.email} value={contact.email}>
                    {contact.name ? `${contact.name} <${contact.email}>` : contact.email}
                  </option>
                ))}
              </SelectInput>
            )}
            <EnvelopePreview
              senderName={currentUser?.name ?? "you"}
              viaEmail={toEmail}
              toEmail={selectedTo || fromEmail}
              subject={subject}
            />
          </>
        )}

        {!isReply && (
          <TextInput
            label="Subject"
            value={noteSubject}
            onChange={(e) => setNoteSubject(e.target.value)}
            placeholder="Short summary shown on the timeline…"
            autoFocus
          />
        )}

        <TextArea
          label={isReply ? "Message to client" : "Note (visible to agents only)"}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={
            isReply ? "Type a reply the client will see…" : "Type a note only agents can see…"
          }
          autoFocus={isReply}
        />

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            isLoading={isLoading}
            disabled={!message.trim() || (!isReply && !noteSubject.trim())}
            onClick={handleSend}
          >
            {isReply ? "Send Reply" : "Add Note"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
