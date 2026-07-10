import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { Card } from "@tw/components/common/Card";
import { Button } from "@tw/components/common/Button";
import { EnvelopePreview } from "@tw/components/common/EnvelopePreview";
import { TextArea } from "@tw/components/common/FormField";
import { useApiAction } from "@tw/hooks/useApiAction";
import { addInternalNote, replyToClient } from "@tw/api/interaction";
import { useAuthContext } from "@tw/context/AuthContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";

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

  if (!activeTicket) return null;

  const isReply = activeMode === "reply";
  const isLoading = isReply ? isReplyLoading : isNoteLoading;
  const toEmail = latestEmail?.payload.to_email as string | undefined;
  const fromEmail = latestEmail?.payload.from_email as string | undefined;
  const subject = latestEmail?.payload.subject as string | undefined;

  async function handleSend() {
    if (!activeTicket || !message.trim()) return;

    const result = isReply
      ? await runReply(activeTicket.ticket_id, { message })
      : await runNote(activeTicket.ticket_id, { note: message });

    if (result) {
      setMessage("");
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
          <EnvelopePreview
            senderName={currentUser?.name ?? "you"}
            viaEmail={toEmail}
            toEmail={fromEmail}
            subject={subject}
          />
        )}

        <TextArea
          label={isReply ? "Message to client" : "Note (visible to agents only)"}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={
            isReply ? "Type a reply the client will see…" : "Type a note only agents can see…"
          }
          autoFocus
        />

        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            isLoading={isLoading}
            disabled={!message.trim()}
            onClick={handleSend}
          >
            {isReply ? "Send Reply" : "Add Note"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
