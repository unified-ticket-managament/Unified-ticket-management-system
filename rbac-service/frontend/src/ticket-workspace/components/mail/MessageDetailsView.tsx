"use client";

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  Clock3,
  ExternalLink,
  FilePlus,
  Forward as ForwardIcon,
  Loader2,
  Paperclip,
  Reply as ReplyIcon,
  ReplyAll,
  UserCog,
  UserPlus,
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useApiAction } from "@tw/hooks/useApiAction";
import { archiveInteraction, claimInteraction, replyToInteraction } from "@tw/api/inbox";
import { listAgents } from "@tw/api/agent";
import { listCategories } from "@tw/api/categories";
import { replyToClient, uploadAttachment } from "@tw/api/interaction";
import {
  attachInteractionToTicket,
  createTicketFromInteraction,
  getTicket,
  listTickets,
  transferTicketAgent,
} from "@tw/api/ticket";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { formatDateTime } from "@tw/lib/format";
import { buildForwardHtml } from "@tw/lib/richText";
import type {
  AgentSummary,
  CategoryResponse,
  InteractionResponse,
  MailFolder,
  OpenEmailResponse,
  TicketPriority,
  TicketResponse,
} from "@tw/types";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { ReplyComposer } from "@tw/components/mail/ReplyComposer";

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
};

const STATUS_META: Record<string, { label: string; variant: "warning" | "success" | "secondary" }> = {
  PENDING: { label: "Pending", variant: "warning" },
  ASSIGNED: { label: "Replied", variant: "success" },
  IGNORED: { label: "Archived", variant: "secondary" },
};

const PRIORITIES: TicketPriority[] = ["LOW", "MEDIUM", "HIGH"];

const SNOOZE_PRESETS: Array<{ label: string; getDate: () => Date }> = [
  { label: "1 hour", getDate: () => new Date(Date.now() + 60 * 60 * 1000) },
  {
    label: "Tomorrow, 9am",
    getDate: () => {
      const d = new Date();
      d.setDate(d.getDate() + 1);
      d.setHours(9, 0, 0, 0);
      return d;
    },
  },
  { label: "1 week", getDate: () => new Date(Date.now() + 7 * 24 * 60 * 60 * 1000) },
];

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
        <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90">{data.body}</p>
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
  onSaveDraft: (interactionId: string, message: string) => Promise<boolean>;
  onSendDraft: (interactionId: string) => Promise<{ interaction_id: string; message: string; created_at: string } | null>;
  onDiscardDraft: (interactionId: string) => Promise<boolean>;
  onSnooze: (interactionId: string, snoozeUntil: string) => Promise<boolean>;
  onUnsnooze: (interactionId: string) => Promise<boolean>;
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
  onSnooze,
  onUnsnooze,
  onUpdateTags,
  onAssignFolder,
}: MessageDetailsViewProps) {
  const { setSelectedEmail } = useWorkflowContext();
  const [replyMode, setReplyMode] = useState<"reply" | "replyAll" | null>(null);
  const [newTag, setNewTag] = useState("");
  const [ticketDetail, setTicketDetail] = useState<TicketResponse | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [categories, setCategories] = useState<CategoryResponse[]>([]);
  const [title, setTitle] = useState("");
  const [ticketType, setTicketType] = useState("");
  const [priority, setPriority] = useState<TicketPriority>("MEDIUM");
  const [existingTicketId, setExistingTicketId] = useState("");
  const [clientTickets, setClientTickets] = useState<TicketResponse[]>([]);
  const [assignAgents, setAssignAgents] = useState<AgentSummary[]>([]);

  const isTicketed = Boolean(email.ticket_id);
  const isClosed = email.ticket_status === "CLOSED";
  const hasDraft = Boolean(email.draft_message);
  const status = STATUS_META[email.status] ?? { label: email.status, variant: "secondary" as const };
  const isSnoozed = Boolean(email.snoozed_until && new Date(email.snoozed_until) > new Date());

  useEffect(() => {
    setReplyMode(null);
    if (email.ticket_id) {
      getTicket(email.ticket_id)
        .then(setTicketDetail)
        .catch(() => setTicketDetail(null));
    } else {
      setTicketDetail(null);
    }
  }, [email.interaction_id, email.ticket_id]);

  useEffect(() => {
    listCategories()
      .then((result) => {
        setCategories(result);
        setTicketType((current) => current || result[0]?.category_name || "");
      })
      .catch(() => {});
  }, []);

  const { run: runReply, isLoading: isReplying } = useApiAction(replyToInteraction);
  const { run: runTicketReply, isLoading: isReplyingTicket } = useApiAction(replyToClient);
  const { run: runUploadAttachment } = useApiAction(uploadAttachment);
  const { run: runCreate, isLoading: isCreating } = useApiAction(createTicketFromInteraction, {
    successMessage: "Ticket created from this email.",
  });
  const { run: runAttach, isLoading: isAttaching } = useApiAction(attachInteractionToTicket, {
    successMessage: "Email attached to existing ticket.",
  });
  const { run: runTransfer, isLoading: isTransferring } = useApiAction(transferTicketAgent, {
    successMessage: (res) => res.message,
  });

  async function handleSend(payload: { message: string; cc: string[]; bcc: string[]; files: File[] }) {
    if (isTicketed && email.ticket_id) {
      const result = await runTicketReply(email.ticket_id, { message: payload.message, cc: payload.cc, bcc: payload.bcc });
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
              interaction_id: result.interaction_id,
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

    const result = await runReply(email.interaction_id, { message: payload.message, cc: payload.cc, bcc: payload.bcc });
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

  async function handleSaveDraft(message: string) {
    await onSaveDraft(email.interaction_id, message);
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
    });
    if (result) {
      setCreateOpen(false);
      onRefreshList();
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
    }
  }

  async function openAssignMenu() {
    if (!ticketDetail) return;
    try {
      const agents = await listAgents(ticketDetail.ticket_type);
      setAssignAgents(agents);
    } catch {
      setAssignAgents([]);
    }
  }

  async function handleTransfer(agentId: string) {
    if (!email.ticket_id) return;
    const result = await runTransfer(email.ticket_id, { new_agent_id: agentId });
    if (result) {
      getTicket(email.ticket_id).then(setTicketDetail).catch(() => {});
      onRefreshList();
    }
  }

  const { run: runClaim, isLoading: isClaiming } = useApiAction(claimInteraction);

  async function handleClaim() {
    const result = await runClaim(email.interaction_id);
    if (result) {
      setSelectedEmail({ ...email, claimed_by: result.claimed_by, claimed_by_name: result.claimed_by_name });
      onRefreshList();
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
  const claimDisabled = isTicketed || Boolean(email.claimed_by) || email.status !== "PENDING" || isClaiming;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card shadow-card">
      <div className="border-b border-border px-5 py-4">
        <button
          onClick={onBack}
          className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Message List
        </button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-[16px] font-semibold text-foreground">{email.subject}</h2>
            <div className="mt-1 flex flex-col gap-0.5 text-[12px] text-muted-foreground sm:flex-row sm:flex-wrap sm:gap-x-4">
              <span>
                From <span className="font-medium text-foreground">{email.from_name || email.client_name}</span>
                {email.from_email && <span className="text-muted-foreground"> &lt;{email.from_email}&gt;</span>}
              </span>
              <span>
                To <span className="font-medium text-foreground">{email.to_email ?? "—"}</span>
              </span>
              <span>{formatDateTime(email.received_at)}</span>
            </div>
          </div>
          <div className="flex flex-none flex-wrap items-center gap-1.5">
            <Badge variant={status.variant}>{status.label}</Badge>
            {email.ticket_priority && (
              <Badge variant={PRIORITY_VARIANT[email.ticket_priority as TicketPriority]}>{email.ticket_priority}</Badge>
            )}
            {email.ticket_category && <Badge variant="secondary">{email.ticket_category}</Badge>}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-b border-border bg-muted/20 px-5 py-2.5">
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

        <Button size="sm" variant="outline" className="gap-1.5" disabled={isTicketed} onClick={() => setCreateOpen(true)}>
          <FilePlus className="h-3.5 w-3.5" />
          Create Ticket
        </Button>

        {isTicketed ? (
          <DropdownMenu onOpenChange={(open) => open && openAssignMenu()}>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5" disabled={isTransferring}>
                <UserCog className="h-3.5 w-3.5" />
                {ticketDetail?.agent_name ? `Assigned: ${ticketDetail.agent_name}` : "Assign Ticket"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-56">
              <DropdownMenuLabel className="text-xs">Assign to</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {assignAgents.length === 0 ? (
                <p className="px-2 py-2 text-xs text-muted-foreground">No agents available.</p>
              ) : (
                assignAgents.map((agent) => (
                  <DropdownMenuItem key={agent.user_id} onClick={() => handleTransfer(agent.user_id)} className="text-xs">
                    {agent.name}
                  </DropdownMenuItem>
                ))
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            disabled={claimDisabled}
            title={email.claimed_by ? `Already assigned to ${email.claimed_by_name ?? "someone"}.` : undefined}
            onClick={handleClaim}
          >
            <UserPlus className="h-3.5 w-3.5" />
            {email.claimed_by ? `Assigned: ${email.claimed_by_name}` : "Assign Ticket"}
          </Button>
        )}

        <Button size="sm" variant="outline" className="gap-1.5" disabled={archiveDisabled} onClick={handleArchive}>
          <Archive className="h-3.5 w-3.5" />
          Archive
        </Button>

        {!isTicketed && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5">
                <Clock3 className="h-3.5 w-3.5" />
                {isSnoozed ? "Snoozed" : "Snooze"}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {isSnoozed ? (
                <DropdownMenuItem onClick={() => onUnsnooze(email.interaction_id)} className="text-xs">
                  Unsnooze
                </DropdownMenuItem>
              ) : (
                SNOOZE_PRESETS.map((preset) => (
                  <DropdownMenuItem
                    key={preset.label}
                    onClick={() => onSnooze(email.interaction_id, preset.getDate().toISOString())}
                    className="text-xs"
                  >
                    {preset.label}
                  </DropdownMenuItem>
                ))
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {email.ticket_id && (
          <Button asChild size="sm" variant="ghost" className="ml-auto gap-1.5 text-primary">
            <Link to={`/tickets/${email.ticket_id}`}>
              View full ticket
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="mb-4 flex flex-wrap items-center gap-2">
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
        </div>

        <div className="flex flex-col gap-3">
          <Bubble data={rootBubble(email)} />
          {email.replies.map((reply) => (
            <Bubble key={reply.interaction_id} data={replyBubble(reply)} />
          ))}
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
          subject={email.subject}
          initialCc={replyMode === "replyAll" ? email.cc : []}
          initialMessage={hasDraft ? email.draft_message ?? "" : ""}
          canAttach={isTicketed}
          canSaveDraft={!isTicketed}
          isSending={isReplying || isReplyingTicket}
          isSavingDraft={false}
          onCancel={() => setReplyMode(null)}
          onSend={handleSend}
          onSaveDraft={handleSaveDraft}
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
            <button
              type="button"
              onClick={() => {
                setCreateOpen(false);
                openAttachDialog();
              }}
              className="text-left text-[11.5px] font-medium text-primary hover:underline"
            >
              Or attach this email to an existing ticket instead →
            </button>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateTicket} disabled={isCreating}>
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
