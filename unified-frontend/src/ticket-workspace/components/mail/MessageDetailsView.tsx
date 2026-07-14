"use client";

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  FilePlus,
  Forward as ForwardIcon,
  Loader2,
  Paperclip,
  Reply as ReplyIcon,
  ReplyAll,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useApiAction } from "@tw/hooks/useApiAction";
import { archiveInteraction, replyToInteraction } from "@tw/api/inbox";
import { listAssignableAgents } from "@tw/api/agent";
import { listClientContacts } from "@tw/api/clients";
import { replyToClient, uploadAttachment } from "@tw/api/interaction";
import { attachInteractionToTicket, createTicketFromInteraction, listTickets } from "@tw/api/ticket";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { formatDateTime } from "@tw/lib/format";
import { buildForwardHtml, linkifyPlainText } from "@tw/lib/richText";
import type {
  AssignableAgentsResponse,
  AttachmentMeta,
  ClientContact,
  DraftSaveResponse,
  InteractionReplyResponse,
  InteractionResponse,
  MailFolder,
  OpenEmailResponse,
  TicketPriority,
  TicketResponse,
} from "@tw/types";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { ReplyComposer } from "@tw/components/mail/ReplyComposer";
import { SlaFirstResponseBadge } from "@tw/components/sla/SlaFirstResponseBadge";

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
  CRITICAL: "destructive",
};

const STATUS_META: Record<string, { label: string; variant: "warning" | "success" | "secondary" }> = {
  PENDING: { label: "Pending", variant: "warning" },
  ASSIGNED: { label: "Replied", variant: "success" },
  IGNORED: { label: "Archived", variant: "secondary" },
};

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

interface BubbleData {
  key: string;
  senderName: string;
  senderEmail: string | null;
  toLabel: string | null;
  timestamp: string;
  body: string;
  isClient: boolean;
  attachments?: OpenEmailResponse["attachments"];
}

function rootBubble(email: OpenEmailResponse): BubbleData {
  return {
    key: email.interaction_id,
    senderName: email.from_name || email.client_name,
    senderEmail: email.from_email,
    toLabel: email.to_email,
    timestamp: email.received_at,
    body: email.body,
    isClient: true,
    // Each message renders its own attachments inline, right where it
    // was sent — not deduplicated into one bucket for the whole thread.
    attachments: email.attachments,
  };
}

function replyBubble(reply: InteractionResponse): BubbleData {
  if (reply.interaction_type === "EMAIL") {
    const payload = reply.payload as { body?: string; from_name?: string; from_email?: string; to_email?: string };
    return {
      key: reply.interaction_id,
      senderName: payload.from_name || payload.from_email || "Client",
      senderEmail: payload.from_email ?? null,
      toLabel: payload.to_email ?? null,
      timestamp: reply.created_at,
      body: payload.body ?? "",
      isClient: true,
      attachments: reply.attachments,
    };
  }
  const payload = reply.payload as {
    message?: string;
    envelope?: { from_name?: string; from_email?: string; to_email?: string };
  };
  return {
    key: reply.interaction_id,
    senderName: payload.envelope?.from_name || "Agent",
    senderEmail: payload.envelope?.from_email ?? null,
    toLabel: payload.envelope?.to_email ?? null,
    timestamp: reply.created_at,
    body: payload.message ?? "",
    isClient: false,
    attachments: reply.attachments,
  };
}

function Bubble({ data }: { data: BubbleData }) {
  return (
    <div className="flex gap-3">
      <div
        className={cn(
          "flex h-8 w-8 flex-none items-center justify-center rounded-full text-[11px] font-semibold",
          data.isClient ? "bg-sky-500/15 text-sky-600" : "bg-primary/15 text-primary"
        )}
      >
        {data.senderName.slice(0, 1).toUpperCase()}
      </div>
      <div className="min-w-0 flex-1 rounded-lg border border-border bg-card px-3.5 py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <p className="text-[13px] font-semibold text-foreground">
            {data.senderName}
            {data.senderEmail && <span className="ml-1.5 font-normal text-muted-foreground">{data.senderEmail}</span>}
          </p>
          <p className="text-[11px] text-muted-foreground">{formatDateTime(data.timestamp)}</p>
        </div>
        {data.toLabel && <p className="mt-0.5 text-[11px] text-muted-foreground">To: {data.toLabel}</p>}
        <div
          className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90 [&_a]:break-all [&_a]:underline"
          dangerouslySetInnerHTML={{ __html: linkifyPlainText(data.body) }}
        />
        {data.attachments && data.attachments.length > 0 && (
          <div className="mt-3 flex flex-col gap-1.5">
            {data.attachments.map((a) => (
              <a
                key={a.id}
                href={a.download_url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-[11.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
              >
                <Paperclip className="h-3 w-3 flex-none text-muted-foreground" />
                <span className="truncate">{a.filename}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface MessageDetailsViewProps {
  email: OpenEmailResponse;
  folders: MailFolder[];
  isSupervisor: boolean;
  onBack: () => void;
  onRefreshList: () => void;
  onForward: (values: { clientId: string | null; toEmail: string; subject: string; bodyHtml: string }) => void;
  onSaveDraft: (
    interactionId: string,
    message: string,
    cc: string[],
    bcc: string[]
  ) => Promise<DraftSaveResponse | null>;
  onSendDraft: (
    interactionId: string,
    toEmail?: string | null
  ) => Promise<InteractionReplyResponse | null>;
  onDiscardDraft: (interactionId: string) => Promise<boolean>;
  onUploadDraftAttachment: (interactionId: string, files: File[]) => Promise<AttachmentMeta[] | null>;
  onRemoveDraftAttachment: (interactionId: string, attachmentId: string) => Promise<boolean>;
  onUpdateTags: (interactionId: string, tags: string[]) => Promise<boolean>;
  onAssignFolder: (interactionId: string, folderId: string | null) => Promise<boolean>;
}

export function MessageDetailsView({
  email,
  folders,
  isSupervisor,
  onBack,
  onRefreshList,
  onForward,
  onSaveDraft,
  onSendDraft,
  onDiscardDraft,
  onUploadDraftAttachment,
  onRemoveDraftAttachment,
  onUpdateTags,
  onAssignFolder,
}: MessageDetailsViewProps) {
  // `categories` used to be fetched independently here on every
  // single mount (i.e. every time a message was opened) — it's now
  // shared, session-wide lookup data fetched once by WorkflowContext
  // instead (see that context's own comment).
  const { setSelectedEmail, categories } = useWorkflowContext();
  const [replyMode, setReplyMode] = useState<"reply" | "replyAll" | null>(null);
  const [newTag, setNewTag] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [ticketType, setTicketType] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [existingTicketId, setExistingTicketId] = useState("");
  const [clientTickets, setClientTickets] = useState<TicketResponse[]>([]);
  const [contacts, setContacts] = useState<ClientContact[]>([]);

  // "Assigned To" picker (Create Ticket dialog) — `assignedToChoice`
  // is either "self" or one of assignableAgents.groups[].role;
  // `selectedAssigneeId` is only meaningful once a role group with
  // more than one candidate is chosen.
  const [assignableAgents, setAssignableAgents] = useState<AssignableAgentsResponse | null>(null);
  const [assignedToChoice, setAssignedToChoice] = useState<string>("self");
  const [selectedAssigneeId, setSelectedAssigneeId] = useState("");

  const isTicketed = Boolean(email.ticket_id);
  const isClosed = email.ticket_status === "CLOSED";
  const hasDraft = Boolean(email.draft_message);
  const status = STATUS_META[email.status] ?? { label: email.status, variant: "secondary" as const };

  useEffect(() => {
    // Opening a thread that already has a saved draft goes straight
    // into edit mode — the user shouldn't have to click Reply first
    // to see (and resume) work they already started.
    setReplyMode(hasDraft ? (email.draft_cc.length > 0 || email.draft_bcc.length > 0 ? "replyAll" : "reply") : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email.interaction_id, email.ticket_id]);

  useEffect(() => {
    if (categories.length > 0) {
      setTicketType((current) => current || categories[0]?.category_name || "");
    }
  }, [categories]);

  useEffect(() => {
    listAssignableAgents()
      .then(setAssignableAgents)
      .catch(() => setAssignableAgents(null));
  }, []);

  // Every personal address this client has ever emailed the shared
  // inbox from — backs the reply composer's "To" dropdown.
  useEffect(() => {
    if (!email.client_id) {
      setContacts([]);
      return;
    }
    listClientContacts(email.client_id)
      .then(setContacts)
      .catch(() => setContacts([]));
  }, [email.client_id]);

  const { run: runReply, isLoading: isReplying } = useApiAction(replyToInteraction);
  const { run: runTicketReply, isLoading: isReplyingTicket } = useApiAction(replyToClient);
  const { run: runUploadAttachment } = useApiAction(uploadAttachment);
  const { run: runCreate, isLoading: isCreating } = useApiAction(createTicketFromInteraction, {
    successMessage: "Ticket created from this email.",
  });
  const { run: runAttach, isLoading: isAttaching } = useApiAction(attachInteractionToTicket, {
    successMessage: "Email attached to existing ticket.",
  });

  const assignedToGroup = assignableAgents?.groups.find((group) => group.role === assignedToChoice) ?? null;
  const needsAssigneePick = Boolean(assignedToGroup);
  const resolvedAgentId =
    assignedToChoice === "self" || !assignedToGroup
      ? assignableAgents?.me.user_id
      : selectedAssigneeId || undefined;

  async function handleSend(payload: {
    message: string;
    cc: string[];
    bcc: string[];
    files: File[];
    to: string | null;
  }) {
    if (isTicketed && email.ticket_id) {
      const result = await runTicketReply(email.ticket_id, {
        message: payload.message,
        cc: payload.cc,
        bcc: payload.bcc,
        to_email: payload.to,
      });
      if (result) {
        if (payload.files.length > 0) {
          await runUploadAttachment(email.ticket_id, payload.files);
        }
        setReplyMode(null);
        onRefreshList();
        setSelectedEmail({
          ...email,
          status: "ASSIGNED",
          draft_message: null,
          replies: [
            ...email.replies,
            {
              // TicketActionResponse.interaction_id is nullable now
              // that status/priority/transfer/claim no longer create
              // one — a reply itself (this call) still always does,
              // so it's safe to assert here.
              interaction_id: result.interaction_id!,
              ticket_id: email.ticket_id,
              interaction_type: "REPLY",
              status: "ASSIGNED",
              direction: "OUTBOUND",
              performed_by: null,
              payload: { message: payload.message },
              is_visible: true,
              removed_by: null,
              removed_at: null,
              message_id: null,
              parent_interaction_id: email.interaction_id,
              created_at: result.created_at,
            },
          ],
        });
      }
      return;
    }

    const result = await runReply(email.interaction_id, {
      message: payload.message,
      cc: payload.cc,
      bcc: payload.bcc,
      to_email: payload.to,
    });
    if (result) {
      setReplyMode(null);
      onRefreshList();
      setSelectedEmail({
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
            payload: { message: payload.message },
            is_visible: true,
            removed_by: null,
            removed_at: null,
            message_id: null,
            parent_interaction_id: result.parent_interaction_id,
            created_at: result.created_at,
          },
        ],
      });
    }
  }

  async function handleSaveDraft(message: string, cc: string[], bcc: string[]) {
    return onSaveDraft(email.interaction_id, message, cc, bcc);
  }

  async function handleSendDraft(toEmail?: string | null) {
    const result = await onSendDraft(email.interaction_id, toEmail);
    if (result) {
      setReplyMode(null);
      onRefreshList();
    }
    return result;
  }

  async function handleDiscardDraft() {
    const result = await onDiscardDraft(email.interaction_id);
    if (result) onRefreshList();
    return result;
  }

  async function handleUploadDraftAttachment(files: File[]) {
    return onUploadDraftAttachment(email.interaction_id, files);
  }

  async function handleRemoveDraftAttachment(attachmentId: string) {
    return onRemoveDraftAttachment(email.interaction_id, attachmentId);
  }

  function handleForwardClick() {
    const bodyHtml = buildForwardHtml({
      fromLabel: email.from_name || email.from_email || email.client_name,
      dateLabel: formatDateTime(email.received_at),
      subject: email.subject,
      body: email.body,
    });
    onForward({
      clientId: email.client_id,
      toEmail: "",
      subject: email.subject.toLowerCase().startsWith("fwd:") ? email.subject : `Fwd: ${email.subject}`,
      bodyHtml,
    });
  }

  async function handleCreateTicket() {
    const result = await runCreate({
      interaction_id: email.interaction_id,
      title: title || email.subject,
      ticket_type: ticketType,
      current_priority: priority,
      agent_id: resolvedAgentId,
    });
    if (result) {
      setCreateOpen(false);
      onRefreshList();
      // Patch the ticket_id onto the open thread immediately so the
      // toolbar's Create Ticket button flips to View Ticket without
      // needing a full refetch of this thread's details.
      setSelectedEmail({ ...email, ticket_id: result.ticket_id, status: "ASSIGNED" });
    }
  }

  async function openAttachDialog() {
    setExistingTicketId(email.recommended_ticket_id ?? "");
    setAttachOpen(true);
    if (!email.client_id) {
      setClientTickets([]);
      return;
    }
    try {
      const all = await listTickets();
      setClientTickets(all.filter((t) => t.client_company_id === email.client_id));
    } catch {
      setClientTickets([]);
    }
  }

  async function handleAttachExisting() {
    if (!existingTicketId) return;
    const result = await runAttach(existingTicketId, { interaction_id: email.interaction_id });
    if (result) {
      setAttachOpen(false);
      onRefreshList();
      setSelectedEmail({ ...email, ticket_id: result.ticket_id, status: "ASSIGNED" });
    }
  }

  const { run: runArchive, isLoading: isArchiving } = useApiAction(archiveInteraction);

  async function handleArchive() {
    const result = await runArchive(email.interaction_id);
    if (result) {
      setSelectedEmail({ ...email, status: result.status });
      onRefreshList();
    }
  }

  async function handleAddTag() {
    const tag = newTag.trim();
    if (!tag || email.tags.includes(tag)) {
      setNewTag("");
      return;
    }
    await onUpdateTags(email.interaction_id, [...email.tags, tag]);
    setNewTag("");
  }

  const archiveDisabled = isTicketed || email.status !== "PENDING" || isArchiving;

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card">
      {/* Message Header — subject, priority/category badges, received date/time */}
      <div className="border-b border-border px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-foreground">{email.subject}</h2>
          <div className="flex flex-none flex-wrap items-center gap-1.5">
            <Badge variant={status.variant}>{status.label}</Badge>
            {email.ticket_priority && (
              <Badge variant={PRIORITY_VARIANT[email.ticket_priority as TicketPriority]}>{email.ticket_priority}</Badge>
            )}
            {email.ticket_category && <Badge variant="secondary">{email.ticket_category}</Badge>}
          </div>
        </div>
        <div className="mt-2">
          <SlaFirstResponseBadge
            receivedAt={email.received_at}
            enabled={!isTicketed && email.status === "PENDING"}
          />
        </div>
        <p className="mt-1.5 text-[12px] text-muted-foreground">{formatDateTime(email.received_at)}</p>
      </div>

      {/* Sender Information / Attachments / Tags / Message Body — the only scrolling region */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="flex flex-col gap-5">
          <section>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Sender Information
            </h3>
            <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-muted/20 p-3 text-[12.5px]">
              <div className="flex gap-2">
                <span className="w-12 flex-none font-medium text-muted-foreground">From</span>
                <span className="min-w-0 flex-1 truncate text-foreground">
                  {email.from_name || email.client_name}
                  {email.from_email && <span className="text-muted-foreground"> &lt;{email.from_email}&gt;</span>}
                </span>
              </div>
              <div className="flex gap-2">
                <span className="w-12 flex-none font-medium text-muted-foreground">To</span>
                <span className="min-w-0 flex-1 truncate text-foreground">{email.to_email ?? "—"}</span>
              </div>
              {email.cc.length > 0 && (
                <div className="flex gap-2">
                  <span className="w-12 flex-none font-medium text-muted-foreground">Cc</span>
                  <span className="min-w-0 flex-1 truncate text-foreground">{email.cc.join(", ")}</span>
                </div>
              )}
              {email.bcc.length > 0 && (
                <div className="flex gap-2">
                  <span className="w-12 flex-none font-medium text-muted-foreground">Bcc</span>
                  <span className="min-w-0 flex-1 truncate text-foreground">{email.bcc.join(", ")}</span>
                </div>
              )}
            </div>
          </section>

          <section className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Tags</span>
            {email.tags.map((tag) => (
              <span
                key={tag}
                className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground/80"
              >
                {tag}
                <button
                  onClick={() => onUpdateTags(email.interaction_id, email.tags.filter((t) => t !== tag))}
                  className="text-muted-foreground hover:text-destructive"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
            <Input
              value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleAddTag();
                }
              }}
              placeholder="Add a tag..."
              className="h-6 w-28 px-2 text-[11px]"
            />

            {!isTicketed && folders.length > 0 && (
              <Select
                value={email.folder_id ?? "__none__"}
                onValueChange={(v) => onAssignFolder(email.interaction_id, v === "__none__" ? null : v)}
              >
                <SelectTrigger className="ml-auto h-7 w-36 text-[11px]">
                  <SelectValue placeholder="Folder" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">No folder</SelectItem>
                  {folders.map((folder) => (
                    <SelectItem key={folder.folder_id} value={folder.folder_id}>
                      {folder.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Message</h3>
            <div className="flex flex-col gap-3">
              <Bubble data={rootBubble(email)} />
              {email.replies.map((reply) => (
                <Bubble key={reply.interaction_id} data={replyBubble(reply)} />
              ))}
            </div>
          </section>
        </div>
      </div>

      {/* Action Toolbar — pinned below the scrolling content, never scrolls out of view */}
      <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-muted/20 px-5 py-2.5">
        <Button size="sm" className="gap-1.5" disabled={isClosed} onClick={() => setReplyMode("reply")}>
          <ReplyIcon className="h-3.5 w-3.5" />
          Reply
        </Button>
        <Button size="sm" variant="outline" className="gap-1.5" disabled={isClosed} onClick={() => setReplyMode("replyAll")}>
          <ReplyAll className="h-3.5 w-3.5" />
          Reply All
        </Button>
        <Button size="sm" variant="outline" className="gap-1.5" onClick={handleForwardClick}>
          <ForwardIcon className="h-3.5 w-3.5" />
          Forward
        </Button>

        <Separator orientation="vertical" className="mx-1 h-5" />

        {isTicketed ? (
          <Button asChild size="sm" variant="outline" className="gap-1.5">
            <Link to={`/tickets/${email.ticket_id}`}>
              <FilePlus className="h-3.5 w-3.5" />
              View Ticket
            </Link>
          </Button>
        ) : (
          <Button size="sm" variant="outline" className="gap-1.5" disabled={isCreating} onClick={() => setCreateOpen(true)}>
            <FilePlus className="h-3.5 w-3.5" />
            Create Ticket
          </Button>
        )}

        <Button size="sm" variant="outline" className="gap-1.5" disabled={archiveDisabled} onClick={handleArchive}>
          <Archive className="h-3.5 w-3.5" />
          Archive
        </Button>

        <div className="ml-auto flex items-center gap-1.5">
          <Button size="sm" variant="ghost" className="gap-1.5" onClick={onBack}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Message List
          </Button>
        </div>
      </div>

      {isClosed && (
        <div className="border-t border-border p-4 text-center text-[12px] text-muted-foreground">
          This ticket is closed — reopen it from the ticket page to reply.
        </div>
      )}

      {!isClosed && replyMode && (
        <ReplyComposer
          mode={replyMode}
          toEmail={email.from_email}
          contacts={contacts}
          subject={email.subject}
          initialCc={hasDraft ? email.draft_cc : replyMode === "replyAll" ? email.cc : []}
          initialBcc={hasDraft ? email.draft_bcc : []}
          initialMessage={hasDraft ? email.draft_message ?? "" : ""}
          isTicketed={isTicketed}
          draftAttachments={email.draft_attachments}
          isSending={isReplying || isReplyingTicket}
          onCancel={() => setReplyMode(null)}
          onSend={handleSend}
          onSaveDraft={handleSaveDraft}
          onSendDraft={handleSendDraft}
          onDiscardDraft={handleDiscardDraft}
          onUploadDraftAttachment={handleUploadDraftAttachment}
          onRemoveDraftAttachment={handleRemoveDraftAttachment}
        />
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Ticket From This Email</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Title</label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={email.subject} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Category</label>
              <Select value={ticketType} onValueChange={setTicketType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((c) => (
                    <SelectItem key={c.category_id} value={c.category_name}>
                      {c.category_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Priority</label>
              <Select value={priority} onValueChange={(v) => setPriority(v as TicketPriority)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITIES.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Assigned To</label>
              {!assignableAgents || assignableAgents.groups.length === 0 ? (
                <Input value={assignableAgents?.me.name ?? "Myself"} readOnly className="bg-muted/30" />
              ) : (
                <div className="flex flex-col gap-2">
                  <Select
                    value={assignedToChoice}
                    onValueChange={(v) => {
                      setAssignedToChoice(v);
                      setSelectedAssigneeId("");
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="self">Myself ({assignableAgents.me.name})</SelectItem>
                      {assignableAgents.groups.map((group) => (
                        <SelectItem key={group.role} value={group.role}>
                          {group.role}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {assignedToGroup && (
                    assignedToGroup.users.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        No {assignedToGroup.role} found in your reporting hierarchy.
                      </p>
                    ) : (
                      <div>
                        <label className="mb-1 block text-xs font-medium text-muted-foreground">
                          Select {assignedToGroup.role}
                        </label>
                        <Select value={selectedAssigneeId} onValueChange={setSelectedAssigneeId}>
                          <SelectTrigger>
                            <SelectValue placeholder={`Choose a ${assignedToGroup.role}...`} />
                          </SelectTrigger>
                          <SelectContent>
                            {assignedToGroup.users.map((user) => (
                              <SelectItem key={user.user_id} value={user.user_id}>
                                {user.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    )
                  )}
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setCreateOpen(false);
                openAttachDialog();
              }}
            >
              Existing Ticket
            </Button>
            <Button
              onClick={handleCreateTicket}
              disabled={
                isCreating ||
                (needsAssigneePick && (assignedToGroup?.users.length === 0 || !selectedAssigneeId))
              }
            >
              {isCreating && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Create Ticket
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={attachOpen} onOpenChange={setAttachOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Attach To Existing Ticket</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            {email.recommended_ticket_id && (
              <div className="rounded-lg border border-primary/20 bg-primary/5 px-3.5 py-2.5 text-xs">
                <p className="font-semibold text-primary">Recommended match found</p>
                <p className="mt-0.5 text-muted-foreground">{email.recommended_ticket_reason}</p>
                <button
                  onClick={() => setExistingTicketId(email.recommended_ticket_id!)}
                  className="mt-1.5 font-medium text-primary hover:underline"
                >
                  Use this ticket
                </button>
              </div>
            )}
            {clientTickets.length > 0 ? (
              <Select value={existingTicketId} onValueChange={setExistingTicketId}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a ticket..." />
                </SelectTrigger>
                <SelectContent>
                  {clientTickets.map((t) => (
                    <SelectItem key={t.ticket_id} value={t.ticket_id}>
                      {t.title} · {t.current_status}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <p className="text-xs text-muted-foreground">No existing tickets found for {email.client_name}.</p>
            )}
            <Input
              value={existingTicketId}
              onChange={(e) => setExistingTicketId(e.target.value)}
              placeholder="Or paste a ticket ID"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttachOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAttachExisting} disabled={isAttaching || !existingTicketId}>
              {isAttaching && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Attach
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
