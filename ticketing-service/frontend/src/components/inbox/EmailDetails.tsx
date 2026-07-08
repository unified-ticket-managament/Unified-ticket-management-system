import { useEffect, useState } from "react";
import { ArrowUpRight, Send, Ticket as TicketIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Avatar } from "@/components/common/Avatar";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Collapsible } from "@/components/common/Collapsible";
import { EmptyState } from "@/components/common/EmptyState";
import { EnvelopePreview } from "@/components/common/EnvelopePreview";
import { AttachmentList } from "@/components/common/AttachmentList";
import { useApiAction } from "@/hooks/useApiAction";
import { replyToInteraction } from "@/api/inbox";
import { replyToClient } from "@/api/interaction";
import { useAuthContext } from "@/context/AuthContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { InteractionReplyResponse, OpenEmailResponse } from "@/types";

interface ReplySent {
  interaction_id: string;
  message: string;
  created_at: string;
}

function appendReply(email: OpenEmailResponse, result: ReplySent): OpenEmailResponse {
  return {
    ...email,
    status: "ASSIGNED",
    draft_message: null,
    replies: [
      ...email.replies,
      {
        interaction_id: result.interaction_id,
        ticket_id: email.ticket_id,
        interaction_type: "REPLY",
        status: "ASSIGNED",
        direction: "OUTBOUND",
        performed_by: null,
        payload: { message: result.message },
        is_visible: true,
        removed_by: null,
        removed_at: null,
        message_id: null,
        parent_interaction_id: email.interaction_id,
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
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const [message, setMessage] = useState("");
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isDiscardingDraft, setIsDiscardingDraft] = useState(false);
  const [isSendingDraft, setIsSendingDraft] = useState(false);

  const { run: runReply, isLoading: isReplying } = useApiAction(replyToInteraction, {
    successMessage: "Reply sent.",
  });
  // Once a thread is ticketed, replying from Mail reuses the exact
  // same backend call TicketComposer uses on the ticket's own page —
  // one reply code path, not a second one duplicated here.
  const { run: runTicketReply, isLoading: isReplyingToTicket } = useApiAction(replyToClient, {
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
  const isClosed = selectedEmail.ticket_status === "CLOSED";
  const hasDraft = Boolean(selectedEmail.draft_message);

  async function handleSaveDraft() {
    if (!selectedEmail || !message.trim()) return;
    setIsSavingDraft(true);
    await onSaveDraft(selectedEmail.interaction_id, message.trim());
    setIsSavingDraft(false);
  }

  async function handleSend() {
    if (!selectedEmail || !message.trim()) return;

    if (isTicketed) {
      // Ticketed thread — no drafts here (those are pre-ticket only),
      // reuse the ticket-level reply endpoint directly.
      const result = await runTicketReply(selectedEmail.ticket_id!, { message: message.trim() });
      if (result) {
        setMessage("");
        setSelectedEmail(appendReply(selectedEmail, result));
      }
      return;
    }

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

      {isClosed ? (
        <div className="border-t border-border p-4 text-center text-[11.5px] text-muted">
          This ticket is closed — reopen it from the ticket page to reply.
        </div>
      ) : (
        <div className="border-t border-border p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              {isTicketed ? "Reply" : "Reply — no ticket needed"}
            </p>
            {!isTicketed && hasDraft && (
              <button
                onClick={handleDiscardDraft}
                disabled={isDiscardingDraft}
                className="text-[10.5px] font-medium text-danger hover:underline disabled:opacity-50"
              >
                Discard draft
              </button>
            )}
          </div>
          <div className="mb-2">
            <EnvelopePreview
              senderName={currentUser?.name ?? "you"}
              viaEmail={selectedEmail.to_email}
              toEmail={selectedEmail.from_email}
              subject={selectedEmail.subject}
            />
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
                isLoading={isReplying || isSendingDraft || isReplyingToTicket}
                disabled={!message.trim()}
                onClick={handleSend}
              >
                <Send size={13} /> Send
              </Button>
              {!isTicketed && (
                <Button
                  variant="ghost"
                  size="sm"
                  isLoading={isSavingDraft}
                  disabled={!message.trim()}
                  onClick={handleSaveDraft}
                >
                  Save draft
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {selectedEmail.ticket_id && (
        // Based on selectedEmail.ticket_id, not the WorkflowContext's
        // activeTicket — opening a thread from Mail never populates
        // activeTicket (that's only set by TicketDetailPage), so this
        // link would silently never show if it depended on that.
        <Link
          to={`/tickets/${selectedEmail.ticket_id}`}
          className="flex items-center gap-2 border-t border-border bg-accent/5 px-5 py-3 text-xs font-medium text-accent transition-colors hover:bg-accent/10"
        >
          <TicketIcon size={13} />
          View full ticket{" "}
          <span className="font-mono">{selectedEmail.ticket_id.slice(0, 8)}…</span>
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
