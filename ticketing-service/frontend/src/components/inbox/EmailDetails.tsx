import { useEffect, useState } from "react";
import { ArrowUpRight, Send, Ticket as TicketIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Avatar } from "@/components/common/Avatar";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Collapsible } from "@/components/common/Collapsible";
import { EmptyState } from "@/components/common/EmptyState";
import { AttachmentList } from "@/components/common/AttachmentList";
import { useApiAction } from "@/hooks/useApiAction";
import { replyToInteraction } from "@/api/inbox";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { InteractionReplyResponse, OpenEmailResponse } from "@/types";

function subjectAsReply(subject: string): string {
  return subject.trim().toLowerCase().startsWith("re:") ? subject : `Re: ${subject}`;
}

function appendReply(email: OpenEmailResponse, result: InteractionReplyResponse): OpenEmailResponse {
  return {
    ...email,
    status: "ASSIGNED",
    draft_message: null,
    replies: [
      ...email.replies,
      {
        interaction_id: result.interaction_id,
        ticket_id: null,
        interaction_type: "REPLY",
        status: "ASSIGNED",
        direction: "OUTBOUND",
        performed_by: null,
        payload: { message: result.message },
        is_visible: true,
        removed_by: null,
        removed_at: null,
        message_id: null,
        parent_interaction_id: result.parent_interaction_id,
        created_at: result.created_at,
      },
    ],
  };
}

interface EmailDetailsProps {
  onSaveDraft: (interactionId: string, message: string) => Promise<boolean>;
  onSendDraft: (interactionId: string) => Promise<InteractionReplyResponse | null>;
  onDiscardDraft: (interactionId: string) => Promise<boolean>;
}

export function EmailDetails({ onSaveDraft, onSendDraft, onDiscardDraft }: EmailDetailsProps) {
  const { selectedEmail, setSelectedEmail, activeTicket } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [message, setMessage] = useState("");
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isDiscardingDraft, setIsDiscardingDraft] = useState(false);
  const [isSendingDraft, setIsSendingDraft] = useState(false);

  const { run: runReply, isLoading: isReplying } = useApiAction(replyToInteraction, {
    successMessage: "Reply sent.",
  });

  // Prefill the composer from this thread's saved draft (if any)
  // whenever the selected email changes — a fresh selection should
  // never carry over text left in the box from the previous one.
  useEffect(() => {
    setMessage(selectedEmail?.draft_message ?? "");
  }, [selectedEmail?.interaction_id]);

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

  const isTicketed = Boolean(selectedEmail.ticket_id);
  const hasDraft = Boolean(selectedEmail.draft_message);

  async function handleSaveDraft() {
    if (!selectedEmail || !message.trim()) return;
    setIsSavingDraft(true);
    await onSaveDraft(selectedEmail.interaction_id, message.trim());
    setIsSavingDraft(false);
  }

  async function handleSend() {
    if (!selectedEmail || !message.trim()) return;

    if (hasDraft) {
      // A draft already exists on this thread — make sure the latest
      // edits are saved before converting it into a real reply, so
      // editing-then-sending in one motion never loses text or
      // leaves a stale draft row behind.
      setIsSendingDraft(true);
      await onSaveDraft(selectedEmail.interaction_id, message.trim());
      const result = await onSendDraft(selectedEmail.interaction_id);
      setIsSendingDraft(false);

      if (result) {
        setMessage("");
        setSelectedEmail(appendReply(selectedEmail, result));
      }
      return;
    }

    const result = await runReply(selectedEmail.interaction_id, { message: message.trim() });

    if (result) {
      setMessage("");
      // Reflect the new reply immediately in the thread without a
      // full refetch — the shared inbox list picks up the status
      // change (PENDING -> ASSIGNED) next time it refreshes.
      setSelectedEmail(appendReply(selectedEmail, result));
    }
  }

  async function handleDiscardDraft() {
    if (!selectedEmail) return;
    setIsDiscardingDraft(true);
    const ok = await onDiscardDraft(selectedEmail.interaction_id);
    setIsDiscardingDraft(false);
    if (ok) setMessage("");
  }

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="flex items-center gap-3">
          <Avatar name={selectedEmail.from_name ?? selectedEmail.client_name} />
          <div className="min-w-0">
            <p className="truncate text-[13px] font-semibold text-slate-900">
              {selectedEmail.from_name ?? selectedEmail.from_email}
            </p>
            <p className="text-[11px] text-muted">{selectedEmail.client_name}</p>
          </div>
        </div>
        <Badge tone={selectedEmail.status === "PENDING" ? "warning" : "success"} dot>
          {selectedEmail.status}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-3 border-b border-border bg-canvas/50 px-5 py-3 text-[11px]">
        <div>
          <p className="text-muted">Via</p>
          <p className="mt-0.5 font-medium text-slate-700">{selectedEmail.to_email ?? "—"}</p>
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
        <p className="mb-1 text-[11px] font-semibold text-muted">{selectedEmail.from_email}</p>
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

        {selectedEmail.replies.length > 0 && (
          <div className="mt-5 flex flex-col gap-3 border-t border-border pt-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Replies
            </p>
            {/* Older replies collapse behind a toggle so the thread
                doesn't force scrolling past every past message just
                to reach the latest one — only the newest stays
                visible by default. */}
            {selectedEmail.replies.length > 1 && (
              <Collapsible title={`${selectedEmail.replies.length - 1} earlier message${selectedEmail.replies.length - 1 === 1 ? "" : "s"}`}>
                <div className="flex flex-col gap-3">
                  {selectedEmail.replies.slice(0, -1).map((reply) => (
                    <ReplyBubble key={reply.interaction_id} message={(reply.payload.message as string) ?? ""} />
                  ))}
                </div>
              </Collapsible>
            )}
            {selectedEmail.replies.slice(-1).map((reply) => (
              <ReplyBubble key={reply.interaction_id} message={(reply.payload.message as string) ?? ""} />
            ))}
          </div>
        )}
      </div>

      {!isTicketed && (
        <div className="border-t border-border p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Reply — no ticket needed
            </p>
            {hasDraft && (
              <button
                onClick={handleDiscardDraft}
                disabled={isDiscardingDraft}
                className="text-[10.5px] font-medium text-danger hover:underline disabled:opacity-50"
              >
                Discard draft
              </button>
            )}
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-md2 bg-canvas px-3 py-2 text-[10.5px] text-muted">
            <span>Sending as</span>
            <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-medium text-slate-700">
              {currentUser?.name ?? "you"}
              {selectedEmail.to_email ? ` · via ${selectedEmail.to_email}` : ""}
            </span>
            {selectedEmail.from_email && (
              <>
                <span>to</span>
                <span className="rounded-full border border-border bg-surface px-2 py-0.5 font-medium text-slate-700">
                  {selectedEmail.from_email}
                </span>
              </>
            )}
            <span className="rounded-full border border-teal/20 bg-teal/10 px-2 py-0.5 font-medium text-teal">
              CC: Account Manager (auto)
            </span>
            <span className="ml-auto">threads as {subjectAsReply(selectedEmail.subject)}</span>
          </div>
          <div className="flex items-end gap-2">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Write a reply to the client..."
              rows={2}
              className="min-h-[44px] flex-1 resize-y rounded-md2 border border-border bg-canvas px-3 py-2 text-sm text-slate-900 placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
            />
            <div className="flex flex-col gap-1.5">
              <Button
                variant="primary"
                size="sm"
                isLoading={isReplying || isSendingDraft}
                disabled={!message.trim()}
                onClick={handleSend}
              >
                <Send size={13} /> Send
              </Button>
              <Button
                variant="ghost"
                size="sm"
                isLoading={isSavingDraft}
                disabled={!message.trim()}
                onClick={handleSaveDraft}
              >
                Save draft
              </Button>
            </div>
          </div>
        </div>
      )}

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

function ReplyBubble({ message }: { message: string }) {
  return (
    <div className="ml-auto max-w-[85%] rounded-md2 border border-accent/20 bg-accent/5 px-4 py-3">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-accent">
        <ArrowUpRight size={12} /> Reply
      </div>
      <p className="whitespace-pre-wrap text-sm text-slate-700">{message}</p>
    </div>
  );
}
