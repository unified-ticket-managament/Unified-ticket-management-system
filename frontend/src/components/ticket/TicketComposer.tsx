import { useState } from "react";
import { X } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { TextArea } from "@/components/common/FormField";
import { useApiAction } from "@/hooks/useApiAction";
import { addInternalNote, replyToClient } from "@/api/interaction";
import { useWorkflowContext } from "@/context/WorkflowContext";

export type ComposerMode = "reply" | "note";

interface TicketComposerProps {
  mode: ComposerMode;
  onClose: () => void;
  onSent: () => void;
}

export function TicketComposer({ mode, onClose, onSent }: TicketComposerProps) {
  const { activeTicket, agentName } = useWorkflowContext();
  const [message, setMessage] = useState("");

  const { run: runReply, isLoading: isReplyLoading } = useApiAction(replyToClient, {
    successMessage: "Reply sent to client.",
  });
  const { run: runNote, isLoading: isNoteLoading } = useApiAction(addInternalNote, {
    successMessage: "Internal note added.",
  });

  if (!activeTicket) return null;

  const isReply = mode === "reply";
  const isLoading = isReply ? isReplyLoading : isNoteLoading;

  async function handleSend() {
    if (!activeTicket || !message.trim()) return;

    const result = isReply
      ? await runReply(activeTicket.ticket_id, { message }, agentName)
      : await runNote(activeTicket.ticket_id, { note: message }, agentName);

    if (result) {
      setMessage("");
      onSent();
    }
  }

  return (
    <Card
      title={isReply ? "Reply to Client" : "Internal Note"}
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
