"use client";

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  ExternalLink,
  FilePlus,
  Forward as ForwardIcon,
  Link2,
  Loader2,
  Paperclip,
  RefreshCw,
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
// Cross-alias imports, deliberately mirroring the same exception
// @tw/context/AuthContext.tsx already makes for auth specifically —
// there is no @tw/-side equivalent for a live /auth/me refetch, and
// this app's own useAuthStore/authService are the actual source of
// truth useAuthContext() itself just re-exposes read-only. See
// handleReplyClick below for why a live refetch (not the frozen
// currentUser above) is needed here.
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { archiveInteraction, replyToInteraction } from "@tw/api/inbox";
import { listAssignableAgents } from "@tw/api/agent";
import { listClientContacts } from "@tw/api/clients";
import { replyToClient, uploadAttachment } from "@tw/api/interaction";
import { attachInteractionToTicket, createTicketFromInteraction, listTickets } from "@tw/api/ticket";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { formatAssigneeLabel, formatDateTime, formatTicketNumber } from "@tw/lib/format";
import { buildForwardHtml, renderThreadedMessageHtml } from "@tw/lib/richText";
import { showUndoSendToast } from "@tw/lib/undoSend";
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
import { ShowMoreToggle } from "@tw/components/common/ShowMoreToggle";
import { useCollapsibleMessage } from "@tw/hooks/useCollapsibleMessage";

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
  CRITICAL: "destructive",
};

// Reply-All's Cc prefill: the original message's own Cc list, plus
// every other address the sender put directly in To (index 0 of
// to_recipients is always the shared mailbox itself, already becoming
// the reply's From) — minus the shared mailbox address and whoever's
// about to be the reply's own To (the sender, already covered there).
// Both source lists are empty for anything that didn't arrive via the
// Graph transport (see OpenEmailResponse.cc/to_recipients), so this
// degrades to "no Cc" exactly like the old email.cc-only behavior did
// for those threads.
function computeReplyAllCc(email: OpenEmailResponse): string[] {
  const exclude = new Set(
    [email.to_email, email.from_email]
      .filter((address): address is string => Boolean(address))
      .map((address) => address.toLowerCase())
  );

  const seen = new Set<string>();
  const result: string[] = [];

  for (const address of [...(email.cc ?? []), ...(email.to_recipients ?? [])]) {
    const key = address.toLowerCase();
    if (exclude.has(key) || seen.has(key)) continue;
    seen.add(key);
    result.push(address);
  }

  return result;
}

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
  // Render once and reuse for both the overflow measurement and the
  // render itself, so "Show More" reflects the rendered length rather
  // than the raw stored body (which may include Outlook's own quoted
  // reply-history headers — see renderThreadedMessageHtml's own
  // comment for how those are shown vs. dropped).
  const renderedBody = renderThreadedMessageHtml(data.body, { name: data.senderName, email: data.senderEmail });
  const { ref, isExpanded, isOverflowing, toggle, clampClassName } = useCollapsibleMessage([renderedBody]);

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
          ref={ref}
          className={cn(
            "mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/90 [&_a]:break-all [&_a]:underline",
            clampClassName
          )}
          dangerouslySetInnerHTML={{ __html: renderedBody }}
        />
        {isOverflowing && <ShowMoreToggle isExpanded={isExpanded} onToggle={toggle} />}
        {data.attachments && data.attachments.length > 0 && (
          <div className="mt-3 flex flex-col gap-1.5">
            {data.attachments.map((a) => (
              <a
                key={a.id}
                href={a.download_url}
                target="_blank"
                rel="noreferrer"
                title={a.is_external_link ? "Opens the original OneDrive/SharePoint link" : undefined}
                className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-[11.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
              >
                {a.is_external_link ? (
                  <ExternalLink className="h-3 w-3 flex-none text-muted-foreground" />
                ) : (
                  <Paperclip className="h-3 w-3 flex-none text-muted-foreground" />
                )}
                <span className="truncate">{a.filename}</span>
                {a.is_external_link && (
                  <span className="flex-none text-[10px] font-normal text-muted-foreground">(link)</span>
                )}
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
  onBack: () => void;
  // "standalone" (default) keeps this component's own card chrome
  // (rounded/border/shadow) for any caller rendering it on its own.
  // "panel" — used by the Outlook-style three-panel Mail workspace,
  // see InboxPage.tsx/MailWorkspaceLayout.tsx — drops that chrome
  // since the workspace's own outer container already supplies it,
  // and a nested card-in-a-panel would read as two separate surfaces
  // instead of one integrated one.
  variant?: "standalone" | "panel";
  onRefreshList: () => void;
  // Re-fetches this specific open message (not the whole list) — see
  // InboxPage.tsx, wired to mail.openThread(interactionId).
  onRefreshMessage: (interactionId: string) => void;
  isRefreshingMessage?: boolean;
  onForward: (values: { clientId: string | null; toEmail: string; subject: string; bodyHtml: string; interactionId: string }) => void;
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
  onBack,
  variant = "standalone",
  onRefreshList,
  onRefreshMessage,
  isRefreshingMessage,
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
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  const canConvertToTicket = !!currentUser?.permissions.includes(
    "communication:convert_to_ticket"
  );
  const canAttachToTicket = !!currentUser?.permissions.includes(
    "communication:attach_to_ticket"
  );
  const canArchive = !!currentUser?.permissions.includes("communication:archive");
  const canReplyExternal = !!currentUser?.permissions.includes(
    "communication:reply_external"
  );
  const [replyMode, setReplyMode] = useState<"reply" | "replyAll" | null>(null);

  // canReplyExternal above is a render-time snapshot of whatever
  // useAuthStore held at login/last refresh — it never re-checks a
  // permission revoked mid-session. This alone still correctly hides
  // the buttons for someone who never had the permission at page
  // load, so it's kept as-is (belt) and the check below is additive
  // (suspenders): re-verify against a fresh GET /auth/me at the
  // moment Reply/Reply All is actually clicked, so a revocation that
  // happened seconds ago is caught before the editor ever opens
  // (rather than only at Send, which stays the unchanged final
  // backend check in interaction_service.py). Reuses this file's own
  // useApiAction convention (loading state + toast-on-error) rather
  // than a hand-rolled boolean.
  const setUser = useAuthStore((s) => s.setUser);
  const replyAccessCheck = useApiAction(async (mode: "reply" | "replyAll") => {
    try {
      const freshUser = await authService.me();
      setUser(freshUser); // keeps every other permission-derived UI in this session in sync too
      const hasFlat = freshUser.permissions.includes("communication:reply_external");
      const hasScoped =
        freshUser.scoped_permissions?.["communication:reply_external"]?.includes(
          email.ticket_id ?? ""
        ) ?? false;
      if (!hasFlat && !hasScoped) throw new Error();
    } catch {
      // Denied, or the /auth/me call itself failed (network error, or
      // a 401 from permission_version drift) — fail closed either
      // way, same message. A genuine 401 is already handled underneath
      // this call by the existing axios refresh/redirect interceptor.
      throw new Error("You no longer have permission to reply to this client.");
    }
    return mode;
  });

  async function handleReplyClick(mode: "reply" | "replyAll") {
    const result = await replyAccessCheck.run(mode);
    if (result) setReplyMode(result);
  }
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
  // is "unassigned", "self", or one of assignableAgents.groups[].role;
  // `selectedAssigneeId` is only meaningful once a role group with
  // more than one candidate is chosen. Defaults to "unassigned" so a
  // ticket created without deliberately picking an assignee lands in
  // the Open Pool as team-scoped work, not silently claimed by its
  // creator.
  const [assignableAgents, setAssignableAgents] = useState<AssignableAgentsResponse | null>(null);
  const [assignableAgentsError, setAssignableAgentsError] = useState(false);
  const [assignedToChoice, setAssignedToChoice] = useState<string>("unassigned");
  const [selectedAssigneeId, setSelectedAssigneeId] = useState("");

  // Attach-to-Ticket's reopen extension: only relevant when the
  // ticket picked in the Attach dialog is CLOSED — mirrors the
  // Create Ticket dialog's own group-then-user picker shape, sourced
  // from GET /tickets/{id}/transfer-candidates (the same eligibility
  // rules InteractionService.transfer_agent enforces server-side) so
  // whatever's offered here is always something the backend will
  // actually accept.
  const [reopenCandidates, setReopenCandidates] = useState<AssignableAgentsResponse | null>(null);
  const [reopenAssignChoice, setReopenAssignChoice] = useState<"keep" | "reassign">("keep");
  const [reopenAssignGroup, setReopenAssignGroup] = useState<string>("");
  const [reopenAssigneeId, setReopenAssigneeId] = useState("");
  const [reopenPriorityChoice, setReopenPriorityChoice] = useState<"keep" | "change">("keep");
  const [reopenPriority, setReopenPriority] = useState<TicketPriority>("MEDIUM");

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

  function loadAssignableAgents(category: string) {
    setAssignableAgentsError(false);
    listAssignableAgents(category || undefined)
      .then(setAssignableAgents)
      .catch(() => {
        setAssignableAgents(null);
        setAssignableAgentsError(true);
      });
  }

  useEffect(() => {
    // Re-fetches whenever the dialog's own Category selection changes
    // (not just once on mount) — the Team Lead/Staff groups are scoped
    // to this category on the backend (see AssignmentService), so a
    // stale, unscoped list would otherwise linger from before the user
    // picked a category. Resets any already-chosen assignee too, since
    // a Team Lead/Staff picked under the old category may not even be
    // in the new category's list. A failed fetch is tracked separately
    // (assignableAgentsError) so it renders as a distinct, retryable
    // error rather than silently collapsing to just "Unassigned (Team)"
    // with no explanation.
    setAssignedToChoice("unassigned");
    setSelectedAssigneeId("");
    loadAssignableAgents(ticketType);
  }, [ticketType]);

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
    assignedToChoice === "unassigned"
      ? undefined
      : assignedToChoice === "self" || !assignedToGroup
        ? assignableAgents?.me?.user_id
        : selectedAssigneeId || undefined;

  const selectedExistingTicket = clientTickets.find((t) => t.ticket_id === existingTicketId) ?? null;
  const isReopeningClosedTicket = selectedExistingTicket?.current_status === "CLOSED";
  const reopenAssignGroupData = reopenCandidates?.groups.find((group) => group.role === reopenAssignGroup) ?? null;
  const resolvedReopenAgentId =
    reopenAssignGroup === "me"
      ? reopenCandidates?.me?.user_id
      : reopenAssignGroupData
        ? reopenAssigneeId || undefined
        : undefined;

  useEffect(() => {
    // Category-based hierarchy (same lookup the Create Ticket dialog's
    // own "Assigned To" picker already uses, see assignableAgents
    // above) — NOT the flat transfer-candidates list, which mirrors
    // transfer_agent's broader company-wide-Team-Lead/no-Staff rules
    // rather than "everyone under this ticket's category." Scoped to
    // the selected existing ticket's own category (its ticket_type),
    // so it returns: this category's Account Manager (the caller
    // themselves, via AssignmentService's own `me` field), every Team
    // Lead in this category, and every Staff member in this category.
    if (!isReopeningClosedTicket || !selectedExistingTicket) {
      setReopenCandidates(null);
      return;
    }
    listAssignableAgents(selectedExistingTicket.ticket_type)
      .then(setReopenCandidates)
      .catch(() => setReopenCandidates(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingTicketId, isReopeningClosedTicket]);

  async function handleSend(payload: {
    message: string;
    cc: string[];
    bcc: string[];
    files: File[];
    to: string | null;
  }) {
    if (isTicketed && email.ticket_id) {
      // Files are uploaded *before* the reply is sent (not after) so
      // the reply can point at them via attachment_source_interaction_id
      // — the backend embeds them in the actual outbound email that
      // way; uploading afterward (the old order) only ever recorded
      // them on the ticket's own timeline, never on the sent mail.
      let attachmentSourceInteractionId: string | null = null;
      if (payload.files.length > 0) {
        const uploadResult = await runUploadAttachment(email.ticket_id, payload.files);
        if (!uploadResult) return;
        attachmentSourceInteractionId = uploadResult.interaction_id;
      }

      const result = await runTicketReply(email.ticket_id, {
        message: payload.message,
        cc: payload.cc,
        bcc: payload.bcc,
        to_email: payload.to,
        attachment_source_interaction_id: attachmentSourceInteractionId,
        reply_all: replyMode === "replyAll",
      });
      if (result) {
        showUndoSendToast(pushToast, result.interaction_id, "Reply sent.");
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
      reply_all: replyMode === "replyAll",
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
      interactionId: email.interaction_id,
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
    setReopenAssignChoice("keep");
    setReopenAssignGroup("");
    setReopenAssigneeId("");
    setReopenPriorityChoice("keep");
    setReopenPriority("MEDIUM");
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
    const result = await runAttach(existingTicketId, {
      interaction_id: email.interaction_id,
      ...(isReopeningClosedTicket && reopenAssignChoice === "reassign" && resolvedReopenAgentId
        ? { new_agent_id: resolvedReopenAgentId }
        : {}),
      ...(isReopeningClosedTicket && reopenPriorityChoice === "change"
        ? { new_priority: reopenPriority }
        : {}),
    });
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
    <div
      className={cn(
        "flex flex-col overflow-hidden",
        variant !== "panel" && "rounded-xl border border-border bg-card shadow-card"
      )}
    >
      {/* Message Header — subject, priority/category badges, received date/time */}
      <div className="border-b border-border px-5 py-4">
        <button
          type="button"
          onClick={onBack}
          className="mb-3 flex w-fit items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-foreground">{email.subject}</h2>
          <div className="flex flex-none flex-wrap items-center gap-1.5">
            <Badge variant={status.variant}>{status.label}</Badge>
            {email.ticket_priority && (
              <Badge variant={PRIORITY_VARIANT[email.ticket_priority as TicketPriority]}>{email.ticket_priority}</Badge>
            )}
            {email.ticket_category && <Badge variant="secondary">{email.ticket_category}</Badge>}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => onRefreshMessage(email.interaction_id)}
              disabled={isRefreshingMessage}
              aria-label="Refresh"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", isRefreshingMessage && "animate-spin")} />
            </Button>
          </div>
        </div>
        <div className="mt-2">
          <SlaFirstResponseBadge
            receivedAt={email.received_at}
            enabled={!isTicketed && email.status === "PENDING"}
            firstResponseSla={email.first_response_sla}
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
        {canReplyExternal && (
          <>
            <Button
              size="sm"
              className="gap-1.5"
              disabled={isClosed || replyAccessCheck.isLoading}
              onClick={() => handleReplyClick("reply")}
            >
              {replyAccessCheck.isLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ReplyIcon className="h-3.5 w-3.5" />
              )}
              Reply
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="gap-1.5"
              disabled={isClosed || replyAccessCheck.isLoading}
              onClick={() => handleReplyClick("replyAll")}
            >
              {replyAccessCheck.isLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ReplyAll className="h-3.5 w-3.5" />
              )}
              Reply All
            </Button>
          </>
        )}
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
          <>
            {canConvertToTicket && (
              <Button size="sm" variant="outline" className="gap-1.5" disabled={isCreating} onClick={() => setCreateOpen(true)}>
                <FilePlus className="h-3.5 w-3.5" />
                Create Ticket
              </Button>
            )}
            {canAttachToTicket && (
              <Button size="sm" variant="outline" className="gap-1.5" disabled={isAttaching} onClick={openAttachDialog}>
                <Link2 className="h-3.5 w-3.5" />
                Link to Existing Ticket
              </Button>
            )}
          </>
        )}

        {canArchive && (
          <Button size="sm" variant="outline" className="gap-1.5" disabled={archiveDisabled} onClick={handleArchive}>
            <Archive className="h-3.5 w-3.5" />
            Archive
          </Button>
        )}
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
          initialCc={hasDraft ? email.draft_cc : replyMode === "replyAll" ? computeReplyAllCc(email) : []}
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
                  <SelectValue placeholder="Select" />
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
                    <SelectItem value="unassigned">Unassigned (Team)</SelectItem>
                    {assignableAgents?.me && (
                      <SelectItem value="self">Myself ({formatAssigneeLabel(assignableAgents.me)})</SelectItem>
                    )}
                    {assignableAgents?.groups.map((group) => (
                      <SelectItem key={group.role} value={group.role}>
                        {group.role}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {assignableAgentsError && (
                  <div className="flex items-center gap-2">
                    <p className="text-xs text-destructive">
                      Couldn't load assignable people — try again.
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={() => loadAssignableAgents(ticketType)}
                    >
                      Retry
                    </Button>
                  </div>
                )}

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
                              {formatAssigneeLabel(user)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateTicket}
              disabled={
                isCreating ||
                !ticketType ||
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
                      {formatTicketNumber(t.ticket_number)} · {t.title} · {t.current_status}
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

            {isReopeningClosedTicket && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3.5 py-2.5 text-xs">
                <div className="mb-2 flex items-center gap-2">
                  <Badge variant="secondary">Closed</Badge>
                  <p className="text-muted-foreground">
                    This ticket is currently Closed. Attaching this email will reopen the ticket
                    and continue the existing conversation.
                  </p>
                </div>

                <div className="mb-3">
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Assignment</label>
                  <Select
                    value={reopenAssignChoice}
                    onValueChange={(v) => {
                      setReopenAssignChoice(v as "keep" | "reassign");
                      setReopenAssignGroup("");
                      setReopenAssigneeId("");
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="keep">Keep Existing Assignee</SelectItem>
                      <SelectItem value="reassign">Reassign</SelectItem>
                    </SelectContent>
                  </Select>

                  {reopenAssignChoice === "reassign" && (
                    <div className="mt-2 flex flex-col gap-2">
                      <Select
                        value={reopenAssignGroup}
                        onValueChange={(v) => {
                          setReopenAssignGroup(v);
                          setReopenAssigneeId("");
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Choose who to assign..." />
                        </SelectTrigger>
                        <SelectContent>
                          {reopenCandidates?.me && (
                            <SelectItem value="me">Myself ({formatAssigneeLabel(reopenCandidates.me)})</SelectItem>
                          )}
                          {reopenCandidates?.groups.map((group) => (
                            <SelectItem key={group.role} value={group.role}>
                              {group.role}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>

                      {reopenAssignGroupData && (
                        reopenAssignGroupData.users.length === 0 ? (
                          <p className="text-xs text-muted-foreground">
                            No {reopenAssignGroupData.role} found for this ticket.
                          </p>
                        ) : (
                          <Select value={reopenAssigneeId} onValueChange={setReopenAssigneeId}>
                            <SelectTrigger>
                              <SelectValue placeholder={`Choose a ${reopenAssignGroupData.role}...`} />
                            </SelectTrigger>
                            <SelectContent>
                              {reopenAssignGroupData.users.map((user) => (
                                <SelectItem key={user.user_id} value={user.user_id}>
                                  {formatAssigneeLabel(user)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        )
                      )}
                    </div>
                  )}
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-muted-foreground">Priority</label>
                  <Select
                    value={reopenPriorityChoice}
                    onValueChange={(v) => setReopenPriorityChoice(v as "keep" | "change")}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="keep">Keep Existing Priority</SelectItem>
                      <SelectItem value="change">Change Priority</SelectItem>
                    </SelectContent>
                  </Select>

                  {reopenPriorityChoice === "change" && (
                    <Select
                      value={reopenPriority}
                      onValueChange={(v) => setReopenPriority(v as TicketPriority)}
                    >
                      <SelectTrigger className="mt-2">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="LOW">Low</SelectItem>
                        <SelectItem value="MEDIUM">Medium</SelectItem>
                        <SelectItem value="HIGH">High</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAttachOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleAttachExisting}
              disabled={
                isAttaching ||
                !existingTicketId ||
                (isReopeningClosedTicket &&
                  reopenAssignChoice === "reassign" &&
                  !resolvedReopenAgentId)
              }
            >
              {isAttaching && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Attach
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
