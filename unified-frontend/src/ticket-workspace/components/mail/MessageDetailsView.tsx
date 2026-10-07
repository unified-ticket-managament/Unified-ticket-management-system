"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  Cog,
  ExternalLink,
  FilePlus,
  FolderInput,
  Forward as ForwardIcon,
  Link2,
  Loader2,
  Mail,
  MailOpen,
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
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { FolderMoveItems } from "@tw/components/mail/FolderMoveItems";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useMailFeatures } from "@tw/hooks/useMailFeatures";
import { ReadReceiptStatus } from "@tw/components/mail/ReadReceiptStatus";
import type { ReadReceiptStatus as ReadReceiptStatusData } from "@tw/types";
// Cross-alias imports, deliberately mirroring the same exception
// @tw/context/AuthContext.tsx already makes for auth specifically —
// there is no @tw/-side equivalent for a live /auth/me refetch, and
// this app's own useAuthStore/authService are the actual source of
// truth useAuthContext() itself just re-exposes read-only. See
// handleReplyClick below for why a live refetch (not the frozen
// currentUser above) is needed here.
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { archiveInteraction, replyToInteraction, uploadDraftInlineImage } from "@tw/api/inbox";
import { listAssignableAgents } from "@tw/api/agent";
import { listClientContacts } from "@tw/api/clients";
import {
  discardTicketReplyDraft,
  downloadAttachmentFile,
  getTicketReplyDraft,
  replyToClient,
  retrySend,
  saveTicketReplyDraft,
  uploadAttachment,
  uploadTicketInlineImage,
} from "@tw/api/interaction";
import { attachInteractionToTicket, createTicketFromInteraction, listTickets } from "@tw/api/ticket";
import {
  AdditionalAssignmentRows,
  type AdditionalAssignmentRow,
} from "@tw/components/mail/AdditionalAssignmentRows";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import { formatAssigneeLabel, formatDateTime, formatTicketNumber } from "@tw/lib/format";
import { generateIdempotencyKey } from "@tw/lib/idempotency";
import {
  RENDERED_MESSAGE_HTML_CLASS,
  RENDERED_MESSAGE_TABLE_BORDER_CLASS,
  buildForwardHtml,
  filterLiveInlineImageIds,
  renderThreadedMessageHtml,
  resolveCidImagesForDisplay,
  type TrackedInlineImage,
} from "@tw/lib/richText";
import { newestFirst } from "@tw/lib/threadOrder";
import { showUndoSendToast } from "@tw/lib/undoSend";
import type { PendingMessageAction } from "@tw/lib/messageActions";
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
  TicketReplyDraftResponse,
  TicketResponse,
} from "@tw/types";
import { AttachmentUploader } from "@tw/components/mail/AttachmentUploader";
import { ReplyComposer } from "@tw/components/mail/ReplyComposer";
import {
  RemindMeToolbarButton,
  ReminderStatusBar,
} from "@tw/components/mail/MailReminderIndicators";
import { SlaFirstResponseBadge } from "@tw/components/sla/SlaFirstResponseBadge";
import { ShowMoreToggle } from "@tw/components/common/ShowMoreToggle";
import { useCollapsibleMessage } from "@tw/hooks/useCollapsibleMessage";

const PRIORITY_VARIANT: Record<TicketPriority, "success" | "warning" | "destructive"> = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "destructive",
  CRITICAL: "destructive",
};

// A reply targets whichever specific message (bubble) was actually
// clicked, never the thread root — see handleReplyClick below. For a
// client-authored bubble (isClient), the natural reply target is that
// message's own sender; for an agent-authored REPLY bubble, the
// sender is always the shared mailbox itself (every outbound reply
// goes From there), so the natural target is instead whoever THAT
// reply was sent To — mirrors the backend's own direction-aware
// resolve_reply_addresses (email_envelope.py).
function defaultReplyToAddress(bubble: BubbleData): string | null {
  return bubble.isClient ? bubble.senderEmail : bubble.toLabel;
}

// The shared mailbox's own address for this specific bubble — the
// arrival address for a client-authored message, or (since every
// outbound reply's From is the shared inbox) this bubble's own
// senderEmail for an agent-authored one. Used only to exclude our own
// address from the Reply-All Cc prefill below.
function sharedMailboxAddress(bubble: BubbleData): string | null {
  return bubble.isClient ? bubble.toLabel : bubble.senderEmail;
}

// Reply-All's Cc prefill, computed from the SPECIFIC message (bubble)
// clicked — never the thread root. bubble.cc is that message's own Cc
// list; bubble.toEmails is that message's own full To-recipient list
// (to_recipients for an inbound client email, to_emails for an
// outbound agent reply) — both minus the shared mailbox address and
// whoever's about to become the reply's own To (already covered
// there). Both source lists are empty for anything that didn't carry
// multi-recipient data, so this degrades to "no Cc" exactly like the
// old root-only, cc-only behavior did for those threads.
function computeReplyAllCc(bubble: BubbleData): string[] {
  const exclude = new Set(
    [sharedMailboxAddress(bubble), defaultReplyToAddress(bubble)]
      .filter((address): address is string => Boolean(address))
      .map((address) => address.toLowerCase())
  );

  const seen = new Set<string>();
  const result: string[] = [];

  for (const address of [...bubble.cc, ...bubble.toEmails]) {
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
  // This message's own interaction_id — always set (not just for a
  // reply) so every bubble is independently addressable as a Reply/
  // Reply All/Forward *source*, never only "the thread root" or "the
  // newest message". See handleReplyClick/handleForwardClick below.
  interactionId: string;
  senderName: string;
  senderEmail: string | null;
  toLabel: string | null;
  // This message's own full To/Cc/Bcc/Subject — not just the display
  // string above — so Reply/Reply All's prefill is computed from
  // whichever specific message was clicked, never the thread root's.
  toEmails: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  timestamp: string;
  body: string;
  // The rich, sanitized-on-the-backend HTML counterpart to `body` —
  // for an agent-authored reply, Outlook-style clipboard paste
  // (pasted tables/images/formatting); for an inbound client email
  // (isClient), the sanitized real HTML the sender's own mail client
  // sent (tables/inline screenshots/formatting included). null/
  // undefined falls back to the existing plain-text rendering
  // (renderThreadedMessageHtml) exactly as before this field existed.
  bodyHtml?: string | null;
  isClient: boolean;
  attachments?: OpenEmailResponse["attachments"];
  // Retry Send affordance — only ever shown on an agent-authored
  // bubble (isClient: false) whose own dispatch_status is "FAILED".
  // See replyBubble below and MessageDetailsView's handleRetrySend —
  // reuses the same `interactionId` field above, now populated for
  // every bubble rather than just reply ones.
  dispatchStatus?: string | null;
  dispatchError?: string | null;
  performedBy?: string | null;
  // Per-recipient read-receipt state (outbound messages only), and
  // whether the message asked for one (stored on its persisted
  // envelope) — shown by <ReadReceiptStatus/> under the "To:" line.
  readReceipts?: ReadReceiptStatusData[];
  readReceiptRequested?: boolean;
}

function rootBubble(email: OpenEmailResponse): BubbleData {
  return {
    key: email.interaction_id,
    interactionId: email.interaction_id,
    senderName: email.from_name || email.client_name,
    senderEmail: email.from_email,
    toLabel: email.to_email,
    toEmails: email.to_emails.length > 0 ? email.to_emails : [email.to_email].filter((a): a is string => Boolean(a)),
    cc: email.cc,
    bcc: email.bcc,
    subject: email.subject,
    timestamp: email.received_at,
    body: email.body,
    bodyHtml: email.body_html ?? null,
    isClient: true,
    // Each message renders its own attachments inline, right where it
    // was sent — not deduplicated into one bucket for the whole thread.
    attachments: email.attachments,
    // Only ever non-empty for an outbound (Compose) root.
    readReceipts: email.read_receipts,
  };
}

function replyBubble(reply: InteractionResponse): BubbleData {
  if (reply.interaction_type === "EMAIL") {
    const payload = reply.payload as {
      body?: string;
      html_body?: string | null;
      from_name?: string;
      from_email?: string;
      to_email?: string;
      to_emails?: string[];
      cc?: string[];
      bcc?: string[];
      subject?: string;
    };
    return {
      key: reply.interaction_id,
      interactionId: reply.interaction_id,
      senderName: payload.from_name || payload.from_email || "Client",
      senderEmail: payload.from_email ?? null,
      toLabel: payload.to_email ?? null,
      toEmails: payload.to_emails?.length ? payload.to_emails : [payload.to_email].filter((a): a is string => Boolean(a)),
      cc: payload.cc ?? [],
      bcc: payload.bcc ?? [],
      subject: payload.subject ?? reply.subject ?? "",
      timestamp: reply.created_at,
      body: payload.body ?? "",
      bodyHtml: payload.html_body ?? null,
      isClient: true,
      attachments: reply.attachments,
    };
  }
  const payload = reply.payload as {
    message?: string;
    body_html?: string | null;
    envelope?: {
      from_name?: string;
      from_email?: string;
      to_email?: string;
      to_emails?: string[];
      cc?: string[];
      bcc?: string[];
      subject?: string;
      read_receipt_requested?: boolean;
    };
  };
  return {
    key: reply.interaction_id,
    interactionId: reply.interaction_id,
    // Only reachable for REPLY today — FORWARD rows are intercepted
    // above the caller of this function and rendered via
    // ForwardActionRow instead (see the "Conversation/Thread Event
    // Model" plan's Phase 1). "System" matches the label this
    // codebase already uses everywhere else for an unattributable/
    // automated actor (AuditLogService.resolve_agent_actor,
    // TicketAttachmentsTab, TicketPropertiesCard) — a real agent
    // reply always has a resolvable envelope.from_name, so this is
    // just a defensive fallback, not an expected case.
    senderName: payload.envelope?.from_name || "System",
    senderEmail: payload.envelope?.from_email ?? null,
    toLabel: payload.envelope?.to_email ?? null,
    toEmails: payload.envelope?.to_emails?.length
      ? payload.envelope.to_emails
      : [payload.envelope?.to_email].filter((a): a is string => Boolean(a)),
    cc: payload.envelope?.cc ?? [],
    bcc: payload.envelope?.bcc ?? [],
    subject: payload.envelope?.subject ?? reply.subject ?? "",
    timestamp: reply.created_at,
    body: payload.message ?? "",
    bodyHtml: payload.body_html ?? null,
    isClient: false,
    attachments: reply.attachments,
    dispatchStatus: reply.dispatch_status,
    dispatchError: reply.dispatch_error,
    performedBy: reply.performed_by,
    readReceipts: reply.read_receipts,
    readReceiptRequested: payload.envelope?.read_receipt_requested === true,
  };
}

interface ForwardRecipient {
  user_id: string;
  name: string | null;
  email: string;
}

interface ForwardActionData {
  key: string;
  // Distinguished purely from data already on the row — never
  // viewer-dependent, so this never differs between two people
  // looking at the same thread (see the approved "Conversation/
  // Thread Event Model" plan's governing principle). A rule-driven
  // forward's payload always carries a "rule_id" key (RuleEngineService.
  // _forward_to_employees), even when its value is null on old data;
  // a manual forward (InteractionService.forward_to_internal_user)
  // never writes that key at all.
  kind: "rule" | "manual";
  timestamp: string;
  actorName: string;
  ruleName: string | null;
  recipients: ForwardRecipient[];
}

function forwardAction(reply: InteractionResponse): ForwardActionData {
  const payload = reply.payload as {
    envelope?: { from_name?: string };
    rule_name?: string | null;
    recipients?: ForwardRecipient[];
  };
  return {
    key: reply.interaction_id,
    kind: "rule_id" in reply.payload ? "rule" : "manual",
    timestamp: reply.created_at,
    actorName: payload.envelope?.from_name || "System",
    ruleName: payload.rule_name ?? null,
    recipients: payload.recipients ?? [],
  };
}

// A rule-driven or manual forward is an automated/administrative
// action performed ON this conversation, not a message a person typed
// into it — rendering it as a normal chat bubble (the previous
// behavior) made a Rule's configured creator look like they'd
// personally sent a message to everyone who can see the thread. This
// renders identically for every viewer; the only thing that varies
// per-viewer is the additive "You received this..." line below, shown
// only when the current viewer is actually one of the forward's real
// recipients — never something that decides whether the row itself
// appears (it always does, for anyone who can see the thread root).
function ForwardActionRow({
  data,
  currentUserId,
}: {
  data: ForwardActionData;
  currentUserId?: string | null;
}) {
  const isRecipient =
    !!currentUserId && data.recipients.some((r) => r.user_id === currentUserId);
  const recipientLabel =
    data.recipients.map((r) => r.name || r.email).join(", ") || "no one (send failed)";
  const Icon = data.kind === "rule" ? Cog : ForwardIcon;

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-1 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-[12px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-semibold uppercase tracking-wide text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
          {data.kind === "rule" ? "Rule Action" : "Manual Forward"}
        </span>
        <span className="text-[11px] text-muted-foreground">{formatDateTime(data.timestamp)}</span>
      </div>
      {isRecipient && (
        <p className="font-medium text-primary">
          You received this forwarded {data.kind === "rule" ? "copy" : "email"}
        </p>
      )}
      {data.kind === "rule" ? (
        <>
          <p className="text-foreground">
            Forwarded to: <span className="font-medium">{recipientLabel}</span>
          </p>
          <p className="text-muted-foreground">
            Rule: {data.ruleName || "Unnamed rule"} · Created by: {data.actorName}
          </p>
        </>
      ) : (
        <>
          <p className="text-foreground">
            Forwarded by: <span className="font-medium">{data.actorName}</span>
          </p>
          <p className="text-muted-foreground">
            To: <span className="font-medium text-foreground">{recipientLabel}</span>
          </p>
        </>
      )}
    </div>
  );
}

function Bubble({
  data,
  canRetry,
  isRetrying,
  onRetrySend,
  canReplyExternal,
  replyDisabled,
  onReply,
  onReplyAll,
  onForward,
}: {
  data: BubbleData;
  canRetry?: boolean;
  isRetrying?: boolean;
  onRetrySend?: (interactionId: string) => void;
  // Outlook-style per-message actions — always targets THIS bubble's
  // own data (never the thread root or the newest message), see
  // handleReplyClick/handleForwardClick below. canReplyExternal/
  // replyDisabled mirror the bottom toolbar's own gating exactly —
  // there is no per-message permission/ACL in this system, only
  // *which message* is targeted varies per bubble.
  canReplyExternal?: boolean;
  replyDisabled?: boolean;
  onReply?: () => void;
  onReplyAll?: () => void;
  onForward?: () => void;
}) {
  // Render once and reuse for both the overflow measurement and the
  // render itself, so "Show More" reflects the rendered length rather
  // than the raw stored body (which may include Outlook's own quoted
  // reply-history headers — see renderThreadedMessageHtml's own
  // comment for how those are shown vs. dropped).
  const renderedBody = data.bodyHtml
    ? resolveCidImagesForDisplay(data.bodyHtml, data.attachments ?? [])
    : renderThreadedMessageHtml(data.body, { name: data.senderName, email: data.senderEmail });
  const { ref, isExpanded, isOverflowing, toggle, clampClassName } = useCollapsibleMessage([renderedBody]);
  const [downloadingAttachmentId, setDownloadingAttachmentId] = useState<string | null>(null);

  async function handleAttachmentDownload(attachmentId: string, filename: string) {
    setDownloadingAttachmentId(attachmentId);
    try {
      await downloadAttachmentFile(attachmentId, filename);
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  return (
    <div className="group/bubble flex gap-3">
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
          <div className="flex flex-none items-center gap-1">
            {(onReply || onReplyAll || onForward) && (
              <div className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover/bubble:opacity-100">
                {canReplyExternal && onReply && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label="Reply"
                        disabled={replyDisabled}
                        onClick={onReply}
                        className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
                      >
                        <ReplyIcon className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Reply</TooltipContent>
                  </Tooltip>
                )}
                {canReplyExternal && onReplyAll && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label="Reply All"
                        disabled={replyDisabled}
                        onClick={onReplyAll}
                        className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
                      >
                        <ReplyAll className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Reply All</TooltipContent>
                  </Tooltip>
                )}
                {onForward && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label="Forward"
                        onClick={onForward}
                        className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <ForwardIcon className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>Forward</TooltipContent>
                  </Tooltip>
                )}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">{formatDateTime(data.timestamp)}</p>
          </div>
        </div>
        {data.toLabel && <p className="mt-0.5 text-[11px] text-muted-foreground">To: {data.toLabel}</p>}
        <ReadReceiptStatus receipts={data.readReceipts} requested={data.readReceiptRequested} />
        {data.dispatchStatus === "FAILED" && (
          <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-1.5 text-[11.5px] text-destructive">
            <span className="font-medium">
              Failed to send{data.dispatchError ? `: ${data.dispatchError}` : "."}
            </span>
            {canRetry && data.interactionId && (
              <Button
                size="sm"
                variant="outline"
                className="h-6 gap-1 border-destructive/40 px-2 text-[11px] text-destructive hover:bg-destructive/10"
                disabled={isRetrying}
                onClick={() => onRetrySend?.(data.interactionId as string)}
              >
                {isRetrying ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                Retry Send
              </Button>
            )}
          </div>
        )}
        {(() => {
          // This message's own regular attachments, shown between its
          // header and its body (Outlook-style). Inline/embedded images
          // (e.g. a signature logo referenced via cid:) already render
          // inside the body via resolveCidImagesForDisplay — don't list
          // them again here.
          const visibleAttachments = data.attachments?.filter((a) => !a.is_inline) ?? [];
          return visibleAttachments.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5 border-b border-border/60 pb-2.5">
            {visibleAttachments.map((a) =>
              a.is_external_link ? (
                <a
                  key={a.id}
                  href={a.download_url}
                  target="_blank"
                  rel="noreferrer"
                  title="Opens the original OneDrive/SharePoint link"
                  className="flex max-w-full items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-[11.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
                >
                  <ExternalLink className="h-3 w-3 flex-none text-muted-foreground" />
                  <span className="truncate">{a.filename}</span>
                  <span className="flex-none text-[10px] font-normal text-muted-foreground">(link)</span>
                </a>
              ) : (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => handleAttachmentDownload(a.id, a.filename)}
                  disabled={downloadingAttachmentId === a.id}
                  className="flex max-w-full items-center gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-left text-[11.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {downloadingAttachmentId === a.id ? (
                    <Loader2 className="h-3 w-3 flex-none animate-spin text-muted-foreground" />
                  ) : (
                    <Paperclip className="h-3 w-3 flex-none text-muted-foreground" />
                  )}
                  <span className="truncate">{a.filename}</span>
                </button>
              )
            )}
          </div>
          );
        })()}
        <div
          ref={ref}
          className={cn(
            "mt-2 text-[13px] leading-relaxed text-foreground/90 [&_a]:break-all [&_a]:underline [&_a]:text-primary",
            // whitespace-pre-wrap only belongs on the plain-text-
            // flattened fallback (renderThreadedMessageHtml), where it
            // preserves runs of spaces/line breaks that were just
            // turned into literal characters — real body_html already
            // carries its own block structure (<p>/<li>/...) and forcing
            // pre-wrap on it instead preserves the *source* HTML's own
            // insignificant whitespace (indentation/newlines between
            // tags), fighting the browser's normal whitespace collapsing
            // for genuine markup. Same branching TicketConversationFeed/
            // InteractionDetailsDrawer/FullInteractionPage already use.
            data.bodyHtml ? RENDERED_MESSAGE_HTML_CLASS : "whitespace-pre-wrap",
            // Table-grid borders only for agent-authored replies — never
            // for the client's own inbound email, whose <table> markup
            // is just as often pure layout scaffolding as a real table.
            data.bodyHtml && !data.isClient && RENDERED_MESSAGE_TABLE_BORDER_CLASS,
            clampClassName
          )}
          dangerouslySetInnerHTML={{ __html: renderedBody }}
        />
        {isOverflowing && <ShowMoreToggle isExpanded={isExpanded} onToggle={toggle} />}
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
  // "fullscreen" — the double-click dedicated reading view (see
  // InboxPage.tsx's fullScreenDetail) — also drops the card chrome
  // (the Dialog it renders inside already supplies a full-bleed
  // surface) and reorders sections: Back + the action toolbar move
  // into one top bar, Sender Information moves above the scroll
  // region alongside the subject/date header, and only the Tags and
  // Message thread remain in the scrolling body.
  variant?: "standalone" | "panel" | "fullscreen";
  onRefreshList: () => void;
  // Re-fetches this specific open message (not the whole list) — see
  // InboxPage.tsx, wired to mail.openThread(interactionId).
  onRefreshMessage: (interactionId: string) => void;
  isRefreshingMessage?: boolean;
  onForward: (values: {
    clientId: string | null;
    toEmail: string;
    subject: string;
    bodyHtml: string;
    interactionId: string;
    originalAttachmentCount: number;
    originalAttachments: AttachmentMeta[];
  }) => void;
  onSaveDraft: (
    interactionId: string,
    message: string,
    cc: string[],
    bcc: string[],
    bodyHtml?: string,
    readReceiptRequested?: boolean,
    subject?: string
  ) => Promise<DraftSaveResponse | null>;
  onSendDraft: (
    interactionId: string,
    toEmails?: string[],
    distributionListIds?: string[],
    idempotencyKey?: string
  ) => Promise<InteractionReplyResponse | null>;
  onDiscardDraft: (interactionId: string) => Promise<boolean>;
  onUploadDraftAttachment: (interactionId: string, files: File[]) => Promise<AttachmentMeta[] | null>;
  onRemoveDraftAttachment: (interactionId: string, attachmentId: string) => Promise<boolean>;
  onUpdateTags: (interactionId: string, tags: string[]) => Promise<boolean>;
  onAssignFolder: (interactionId: string, folderId: string | null) => Promise<boolean>;
  onMarkRead: (interactionId: string) => void;
  onMarkUnread: (interactionId: string) => void;
  // The one message within this thread to highlight/scroll-to (set by
  // clicking a specific thread-child row in MessageList) — null shows
  // the conversation with nothing individually singled out.
  selectedMessageId?: string | null;
  // An action picked from a message row's "More actions" menu
  // (MessageActionsMenu.tsx) for this message — run through this
  // view's own toolbar handlers below, then cleared.
  pendingAction?: PendingMessageAction | null;
  onPendingActionHandled?: () => void;
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
  onMarkRead,
  onMarkUnread,
  onUpdateTags,
  onAssignFolder,
  pendingAction = null,
  onPendingActionHandled,
  selectedMessageId = null,
}: MessageDetailsViewProps) {
  // `categories` used to be fetched independently here on every
  // single mount (i.e. every time a message was opened) — it's now
  // shared, session-wide lookup data fetched once by WorkflowContext
  // instead (see that context's own comment).
  const {
    setSelectedEmail,
    allCategories,
    allCategoriesLoading,
    allCategoriesError,
  } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();
  // ticket:create is the canonical permission for this button (RBAC
  // Enforcement Audit, Phase 18/BD-6) — communication:convert_to_ticket
  // was the same capability under a different name and has been
  // superseded here, though its own catalog row is left in place.
  const canConvertToTicket = !!currentUser?.permissions.includes(
    "ticket:create"
  );
  const canAttachToTicket = !!currentUser?.permissions.includes(
    "communication:attach_to_ticket"
  );
  const canArchive = !!currentUser?.permissions.includes("communication:archive");
  const canReplyExternal = !!currentUser?.permissions.includes(
    "communication:reply_external"
  );
  // RBAC Enforcement Audit, Phase 30: mirrors the backend's own gate in
  // AssignmentService.resolve_target (assignment_service.py:230), which
  // is reached only when assigning a newly-created ticket to someone
  // OTHER than the creator — self-assignment and leaving it unassigned
  // both bypass that check entirely and stay ungated here too. Additive
  // onto the existing hierarchy-scoped assignableAgents.groups list
  // (AssignmentService.get_assignable_groups), never a replacement for
  // it — kept deliberately separate from ticket:create and
  // ticket:transfer, per the audit's Phase 29 finding that all three
  // protect independent capabilities.
  const canAssignTicket = !!currentUser?.permissions.includes("ticket:assign");
  const isFullscreen = variant === "fullscreen";
  // Which message is being replied to, and in which mode — Outlook-
  // style, this is always the SPECIFIC bubble the user clicked Reply/
  // Reply All on (see handleReplyClick), never implicitly "the thread
  // root" or "the newest message". The composer itself is still
  // rendered once, directly under whichever bubble this names (see
  // the thread render below).
  const [activeReply, setActiveReply] = useState<{ bubble: BubbleData; mode: "reply" | "replyAll" } | null>(null);
  // See handleUploadInlineImage/handleSend below — only ever
  // populated for a ticketed reply's pasted images. Tracked as
  // {interactionId, contentId} pairs so a deleted/replaced image can
  // be filtered back out at Send time via filterLiveInlineImageIds.
  const pastedImageInteractionIdsRef = useRef<TrackedInlineImage[]>([]);
  // One Send idempotency key per open thread, not one per click — a
  // double-click (or a manual retry after a failure) must reuse the
  // same key so the backend's own dedup (a unique index on the key)
  // can actually collapse them. This component instance is reused
  // across different opened emails (InboxPage.tsx renders it with no
  // `key` prop), so the key is explicitly regenerated whenever the
  // open thread changes (effect below) and after a successful send —
  // never left stable across two different logical messages.
  const idempotencyKeyRef = useRef<string>(generateIdempotencyKey());
  useEffect(() => {
    idempotencyKeyRef.current = generateIdempotencyKey();
  }, [email.interaction_id]);

  // Scrolls to and (via the wrapper className above) highlights whichever
  // single message was just selected from a thread-child click.
  useEffect(() => {
    if (!selectedMessageId) return;
    document
      .getElementById(`mail-message-${selectedMessageId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [selectedMessageId, email.interaction_id]);

  // Retry Send (P1) — reuses the persisted envelope server-side, see
  // InteractionService.retry_failed_send. Refreshes just this one
  // open message afterward (not the whole list) so the bubble's own
  // dispatch_status/dispatch_error reflect the outcome. useApiAction
  // already pushes its own error toast and never rejects — a `null`
  // result is the failure signal, success gets its own toast here.
  const retryAction = useApiAction((interactionId: string) => retrySend(interactionId));
  const handleRetrySend = (interactionId: string) => {
    retryAction.run(interactionId).then((result) => {
      if (result) {
        onRefreshMessage(email.interaction_id);
        pushToast("Retrying send.", "info");
      }
    });
  };

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
  const refreshUser = useAuthStore((s) => s.refreshUser);
  const replyAccessCheck = useApiAction(async (mode: "reply" | "replyAll") => {
    try {
      const freshUser = await authService.me();
      refreshUser(freshUser); // keeps every other permission-derived UI in this session in sync too (merges — never reverts a just-dragged Mail panel width)
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

  // Reply / Reply All scroll-into-view. The composer is mounted
  // conditionally (activeReply), inline under whichever bubble it
  // targets, so a user scrolled elsewhere in a long thread would
  // otherwise have it open off-screen. The
  // tick is bumped only by an explicit Reply / Reply All click — never by
  // the auto-open of a saved draft when a thread is opened — and the
  // effect runs after the commit that mounted the composer, so the ref is
  // populated. scrollIntoView moves only the composer's scrollable
  // ancestors, and the wrapper is never re-keyed, so draft state is kept.
  const replyComposerRef = useRef<HTMLDivElement>(null);
  const [replyScrollTick, setReplyScrollTick] = useState(0);
  useEffect(() => {
    if (replyScrollTick === 0) return;
    replyComposerRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [replyScrollTick]);

  async function handleReplyClick(bubble: BubbleData, mode: "reply" | "replyAll") {
    const result = await replyAccessCheck.run(mode);
    if (result) {
      setActiveReply({ bubble, mode: result });
      setReplyScrollTick((tick) => tick + 1);
    }
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
  // Multi-assignment: extra (secondary) assignees, each picked FOR a
  // category (the ticket also joins every category used here). The
  // primary is always the "Assigned To" pick above.
  const [additionalRows, setAdditionalRows] = useState<AdditionalAssignmentRow[]>([]);

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
  const [ticketReplyDraft, setTicketReplyDraft] = useState<TicketReplyDraftResponse | null>(null);
  const status = STATUS_META[email.status] ?? { label: email.status, variant: "secondary" as const };

  useEffect(() => {
    // Opening a thread that already has a saved draft goes straight
    // into edit mode — the user shouldn't have to click Reply first
    // to see (and resume) work they already started. A draft has no
    // per-message concept of its own (it's inherently "the next reply
    // on this thread"), so it always targets the root bubble — a
    // deliberate, stated limitation, not an oversight.
    setActiveReply(
      hasDraft
        ? {
            bubble: rootBubble(email),
            mode: email.draft_cc.length > 0 || email.draft_bcc.length > 0 ? "replyAll" : "reply",
          }
        : null
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [email.interaction_id, email.ticket_id]);

  // Ticketed counterpart of the effect above — OpenEmailResponse's
  // own draft_message/draft_cc/draft_bcc fields are populated purely
  // from the pre-ticket draft path (InteractionRepository.get_draft),
  // never a ticket-scoped one, so a ticketed thread's saved draft (if
  // any) is fetched here instead and pre-fills ReplyComposer via
  // ticketReplyDraft below. A 404 (no draft) is expected, not an
  // error. Only the first saved "To" recipient is restored here
  // (ReplyComposer's own `toEmail` prop is still a single address) —
  // a known, minor gap versus a multi-recipient ticket draft; subject/
  // body/Cc/Bcc all restore in full.
  useEffect(() => {
    if (!isTicketed || !email.ticket_id) {
      setTicketReplyDraft(null);
      return;
    }
    let cancelled = false;
    getTicketReplyDraft(email.ticket_id)
      .then((draft) => {
        if (cancelled) return;
        setTicketReplyDraft(draft);
        // Same root-only limitation as the pre-ticket draft effect above.
        setActiveReply({
          bubble: rootBubble(email),
          mode: draft.cc.length > 0 || draft.bcc.length > 0 ? "replyAll" : "reply",
        });
      })
      .catch(() => {
        if (!cancelled) setTicketReplyDraft(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isTicketed, email.ticket_id]);

  // Only the most recent request may write state: a slow response for a
  // previously selected category must never overwrite the list for the
  // category now selected.
  const assignableRequestId = useRef(0);

  function loadAssignableAgents(category: string) {
    const requestId = ++assignableRequestId.current;
    setAssignableAgentsError(false);
    listAssignableAgents(category || undefined)
      .then((response) => {
        if (requestId === assignableRequestId.current) setAssignableAgents(response);
      })
      .catch(() => {
        if (requestId !== assignableRequestId.current) return;
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

  // Whether the backend has read receipts switched on (hidden when off).
  const { read_receipts_enabled: readReceiptsEnabled } = useMailFeatures();

  const { run: runReply, isLoading: isReplying } = useApiAction(replyToInteraction);
  const { run: runTicketReply, isLoading: isReplyingTicket } = useApiAction(replyToClient);
  const { run: runUploadAttachment, isLoading: isUploadingAttachment } = useApiAction(uploadAttachment);
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

  // Only fully-picked rows are sent; the primary is never repeated.
  const completeAdditionalRows = additionalRows.filter(
    (row) => row.category_name && row.user_id && row.user_id !== resolvedAgentId
  );
  const additionalRowsNeedPrimary = completeAdditionalRows.length > 0 && !resolvedAgentId;

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
    bodyHtml?: string;
    cc: string[];
    bcc: string[];
    files: File[];
    to: string[];
    distributionListIds: string[];
    readReceiptRequested?: boolean;
    subject: string;
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

      // Only submit ids for images still actually present (as a real
      // cid: reference) in the body being sent — a paste-then-delete/
      // replace/undo before Send must not resurrect a stale
      // attachment. See lib/richText.ts's filterLiveInlineImageIds.
      const liveInlineImageInteractionIds = filterLiveInlineImageIds(
        payload.bodyHtml ?? "",
        pastedImageInteractionIdsRef.current
      );

      const result = await runTicketReply(email.ticket_id, {
        message: payload.message,
        body_html: payload.bodyHtml,
        cc: payload.cc,
        bcc: payload.bcc,
        to_emails: payload.to,
        distribution_list_ids: payload.distributionListIds,
        attachment_source_interaction_id: attachmentSourceInteractionId,
        reply_all: activeReply?.mode === "replyAll",
        subject: payload.subject,
        source_interaction_id: activeReply?.bubble.interactionId,
        inline_image_interaction_ids: liveInlineImageInteractionIds,
        idempotency_key: idempotencyKeyRef.current,
        // Only when ticked, so an ordinary reply's request is unchanged.
        ...(payload.readReceiptRequested ? { read_receipt_requested: true } : {}),
      });
      if (result) {
        idempotencyKeyRef.current = generateIdempotencyKey();
        pastedImageInteractionIdsRef.current = [];
        // The reply just sent through the normal path above — any
        // draft this session had been autosaving for this ticket is
        // now obsolete. Best-effort: a 404 (nothing was ever saved)
        // is expected, not an error.
        discardTicketReplyDraft(email.ticket_id).catch(() => {});
        showUndoSendToast(pushToast, result.interaction_id, "Reply sent.");
        setActiveReply(null);
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
              parent_interaction_id: activeReply?.bubble.interactionId ?? email.interaction_id,
              created_at: result.created_at,
            },
          ],
        });
      }
      return;
    }

    const result = await runReply(email.interaction_id, {
      message: payload.message,
      body_html: payload.bodyHtml,
      cc: payload.cc,
      bcc: payload.bcc,
      to_emails: payload.to,
      distribution_list_ids: payload.distributionListIds,
      reply_all: activeReply?.mode === "replyAll",
      subject: payload.subject,
      source_interaction_id: activeReply?.bubble.interactionId,
      idempotency_key: idempotencyKeyRef.current,
      ...(payload.readReceiptRequested ? { read_receipt_requested: true } : {}),
    });
    if (result) {
      idempotencyKeyRef.current = generateIdempotencyKey();
      setActiveReply(null);
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

  async function handleSaveDraft(
    message: string,
    cc: string[],
    bcc: string[],
    bodyHtml?: string,
    readReceiptRequested?: boolean,
    subject?: string
  ) {
    if (isTicketed && email.ticket_id) {
      return saveTicketReplyDraft(email.ticket_id, {
        message,
        cc,
        bcc,
        body_html: bodyHtml,
        subject,
        ...(readReceiptRequested ? { read_receipt_requested: true } : {}),
      });
    }
    // `subject` is appended only when the composer supplied one, so the
    // call keeps its historical shape otherwise.
    return subject === undefined
      ? onSaveDraft(email.interaction_id, message, cc, bcc, bodyHtml, readReceiptRequested)
      : onSaveDraft(email.interaction_id, message, cc, bcc, bodyHtml, readReceiptRequested, subject);
  }

  async function handleUploadInlineImage(file: File) {
    if (isTicketed && email.ticket_id) {
      const result = await uploadTicketInlineImage(email.ticket_id, file);
      // Unlike the pre-ticket draft path (whose pasted images already
      // share the draft's own interaction_id, reassigned onto the
      // reply wholesale by send_draft's existing mechanism), a
      // ticketed reply's pasted image lands on its own fresh
      // interaction that must be explicitly submitted back at Send
      // time — see handleSend's inline_image_interaction_ids below.
      pastedImageInteractionIdsRef.current.push({
        interactionId: result.interaction_id,
        contentId: result.content_id,
      });
      return { attachmentId: result.id, contentId: result.content_id };
    }
    const result = await uploadDraftInlineImage(email.interaction_id, file);
    return { attachmentId: result.id, contentId: result.content_id };
  }

  async function handleSendDraft(toEmails?: string[], distributionListIds?: string[]) {
    const result = await onSendDraft(
      email.interaction_id,
      toEmails,
      distributionListIds,
      idempotencyKeyRef.current
    );
    if (result) {
      idempotencyKeyRef.current = generateIdempotencyKey();
      setActiveReply(null);
      onRefreshList();
    }
    return result;
  }

  async function handleDiscardDraft() {
    if (isTicketed && email.ticket_id) {
      const result = await discardTicketReplyDraft(email.ticket_id);
      if (result) onRefreshList();
      return result;
    }
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

  // Forward always operates on the SPECIFIC bubble clicked — never
  // implicitly the thread root — so forwarding an older message in a
  // long thread forwards that message's own body/attachments, not the
  // original email's.
  function handleForwardClick(bubble: BubbleData) {
    const bodyHtml = buildForwardHtml({
      fromLabel: bubble.senderName,
      dateLabel: formatDateTime(bubble.timestamp),
      subject: bubble.subject,
      body: bubble.body,
      bodyHtml: bubble.bodyHtml ?? undefined,
    });
    onForward({
      clientId: email.client_id,
      toEmail: "",
      subject: bubble.subject.toLowerCase().startsWith("fwd:") ? bubble.subject : `Fwd: ${bubble.subject}`,
      bodyHtml,
      interactionId: bubble.interactionId,
      originalAttachmentCount: bubble.attachments?.length ?? 0,
      originalAttachments: bubble.attachments ?? [],
    });
  }

  async function handleCreateTicket() {
    const result = await runCreate({
      interaction_id: email.interaction_id,
      title: title || email.subject,
      ticket_type: ticketType,
      current_priority: priority,
      agent_id: resolvedAgentId,
      additional_assignments: completeAdditionalRows.map((row) => ({
        category_name: row.category_name,
        user_id: row.user_id,
      })),
    });
    if (result) {
      setCreateOpen(false);
      setAdditionalRows([]);
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
  // The thread root as a BubbleData — computed once per render and
  // reused for its own Bubble, its own per-message action handlers,
  // and the root-only draft-resume effects above, rather than calling
  // rootBubble(email) repeatedly.
  const rootBubbleData = rootBubble(email);

  // Row-menu hand-off: same guards as the toolbar buttons below, so a
  // menu pick can never do what the matching button would refuse to.
  // The backend still re-checks every one of these.
  useEffect(() => {
    if (!pendingAction || pendingAction.interactionId !== email.interaction_id) return;
    onPendingActionHandled?.();
    switch (pendingAction.action) {
      case "reply":
      case "replyAll":
        if (!canReplyExternal) break;
        if (isClosed) {
          pushToast("This ticket is closed — replies are disabled.", "info");
          break;
        }
        handleReplyClick(rootBubbleData, pendingAction.action);
        break;
      case "forward":
        handleForwardClick(rootBubbleData);
        break;
      case "createTicket":
        if (canConvertToTicket && !isTicketed) setCreateOpen(true);
        break;
      case "linkTicket":
        if (canAttachToTicket && !isTicketed) openAttachDialog();
        break;
      case "archive":
        if (canArchive && !archiveDisabled) handleArchive();
        break;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAction, email.interaction_id]);

  // Renders the Reply/Reply All composer immediately under whichever
  // bubble it's currently targeting (bubbleKey) — Outlook opens its
  // reply editor inline under the message you clicked Reply on, not
  // pinned at the top of the thread. Returns null everywhere else, so
  // exactly one instance of ReplyComposer is ever mounted at a time.
  // Save/Send/Discard Draft remain thread-scoped regardless of which
  // bubble is targeted (there is no per-message draft concept in this
  // system) — a saved draft always resumes against the root bubble
  // (see the two auto-open effects above), which is why its prefill
  // values below are only applied when targeting the root.
  function renderReplyComposerFor(bubbleKey: string) {
    if (isClosed || !activeReply || activeReply.bubble.key !== bubbleKey) return null;
    const { bubble, mode } = activeReply;
    const isRoot = bubble.key === email.interaction_id;
    return (
      <div ref={replyComposerRef} className="scroll-mt-3 mt-2">
        <ReplyComposer
          mode={mode}
          toEmail={isRoot && ticketReplyDraft ? ticketReplyDraft.to_email : defaultReplyToAddress(bubble)}
          contacts={contacts}
          subject={bubble.subject}
          initialSubject={
            isRoot && ticketReplyDraft
              ? ticketReplyDraft.subject
              : isRoot && hasDraft
                ? email.draft_subject
                : null
          }
          initialCc={
            isRoot && ticketReplyDraft
              ? ticketReplyDraft.cc
              : isRoot && hasDraft
                ? email.draft_cc
                : mode === "replyAll"
                  ? computeReplyAllCc(bubble)
                  : []
          }
          initialBcc={isRoot && ticketReplyDraft ? ticketReplyDraft.bcc : isRoot && hasDraft ? email.draft_bcc : []}
          initialMessage={
            isRoot && ticketReplyDraft ? ticketReplyDraft.message : isRoot && hasDraft ? email.draft_message ?? "" : ""
          }
          initialBodyHtml={
            isRoot && ticketReplyDraft ? ticketReplyDraft.body_html : isRoot && hasDraft ? email.draft_body_html : null
          }
          hasExistingDraft={isRoot && (Boolean(ticketReplyDraft) || hasDraft)}
          readReceiptsEnabled={readReceiptsEnabled}
          initialReadReceiptRequested={
            isRoot && ticketReplyDraft
              ? Boolean(ticketReplyDraft.read_receipt_requested)
              : isRoot && hasDraft
                ? Boolean(email.draft_read_receipt_requested)
                : false
          }
          isTicketed={isTicketed}
          draftAttachments={email.draft_attachments}
          isSending={isReplying || isReplyingTicket || isUploadingAttachment}
          onCancel={() => setActiveReply(null)}
          onSend={handleSend}
          onSaveDraft={handleSaveDraft}
          onSendDraft={handleSendDraft}
          onDiscardDraft={handleDiscardDraft}
          onUploadDraftAttachment={handleUploadDraftAttachment}
          onRemoveDraftAttachment={handleRemoveDraftAttachment}
          onUploadInlineImage={handleUploadInlineImage}
        />
      </div>
    );
  }

  // Shared between the bottom-pinned toolbar (panel/standalone) and
  // the top toolbar (fullscreen, see the "isFullscreen" branch below)
  // — same buttons/handlers either way, just rendered in a different
  // structural position.
  const toolbarActions = (
    <>
      {canReplyExternal && (
        <>
          <Button
            size="sm"
            className="gap-1.5"
            disabled={isClosed || replyAccessCheck.isLoading}
            onClick={() => handleReplyClick(rootBubbleData, "reply")}
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
            onClick={() => handleReplyClick(rootBubbleData, "replyAll")}
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
      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => handleForwardClick(rootBubbleData)}>
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

      {!isTicketed && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" className="gap-1.5">
              <FolderInput className="h-3.5 w-3.5" />
              Move to
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {folders.length === 0 ? (
              <DropdownMenuItem disabled>
                No folders yet — create one from the sidebar
              </DropdownMenuItem>
            ) : (
              <>
                <DropdownMenuLabel>Move to folder</DropdownMenuLabel>
                <FolderMoveItems
                  kind="dropdown"
                  folders={folders}
                  currentFolderId={email.folder_id}
                  onPick={(folderId) => onAssignFolder(email.interaction_id, folderId)}
                />
                {email.folder_id && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={() => onAssignFolder(email.interaction_id, null)}>
                      Unfiled
                    </DropdownMenuItem>
                  </>
                )}
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      <Button
        size="sm"
        variant="outline"
        className="gap-1.5"
        onClick={() =>
          email.is_read ? onMarkUnread(email.interaction_id) : onMarkRead(email.interaction_id)
        }
      >
        {email.is_read ? <MailOpen className="h-3.5 w-3.5" /> : <Mail className="h-3.5 w-3.5" />}
        {email.is_read ? "Mark as Unread" : "Mark as Read"}
      </Button>

      <RemindMeToolbarButton interactionId={email.interaction_id} />
    </>
  );

  // Shared between the in-scroll placement (panel/standalone) and the
  // pinned-above-the-scroll-region placement (fullscreen, see the
  // "isFullscreen" branch below) — same From/To/Cc/Bcc content either
  // way, just rendered in a different structural position.
  const senderInfoSection = (
    <section>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        Sender Information
      </h3>
      <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-muted/20 p-3 text-[12.5px]">
        <div className="flex gap-2">
          <span className="w-12 flex-none font-medium text-muted-foreground">From</span>
          <span className="min-w-0 flex-1 truncate text-foreground">
            {email.from_name || (email.category_id ? email.category_name : email.client_name)}
            {email.from_email && <span className="text-muted-foreground"> &lt;{email.from_email}&gt;</span>}
          </span>
        </div>
        <div className="flex gap-2">
          <span className="w-12 flex-none font-medium text-muted-foreground">To</span>
          <span className="min-w-0 flex-1 truncate text-foreground">
            {email.to_emails.length > 0 ? email.to_emails.join(", ") : email.to_email ?? "—"}
          </span>
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
  );

  return (
    <TooltipProvider delayDuration={300}>
    <div
      className={cn(
        "flex flex-col overflow-hidden",
        variant === "standalone" && "rounded-xl border border-border bg-card shadow-card"
      )}
    >
      {/* Fullscreen reading view only — a single top bar combining the
          Back control with the same action toolbar shown at the bottom
          for panel/standalone, so double-clicking an email reads as a
          dedicated reading surface instead of the same panel stretched
          to the viewport. */}
      {isFullscreen && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/20 px-5 py-2.5 pr-14">
          <button
            type="button"
            onClick={onBack}
            className="flex flex-none items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
          >
            <ArrowLeft size={14} />
            Back to Inbox
          </button>
          <div className="flex flex-wrap items-center gap-1.5">{toolbarActions}</div>
        </div>
      )}

      {/* Message Header — subject, priority/category badges, received date/time */}
      <div className="border-b border-border px-5 py-4">
        {!isFullscreen && (
          <button
            type="button"
            onClick={onBack}
            className="mb-3 flex w-fit items-center gap-1.5 text-xs font-semibold text-muted transition-colors hover:text-slate-900"
          >
            <ArrowLeft size={14} />
            Back
          </button>
        )}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-foreground">{email.subject}</h2>
          <div className="flex flex-none flex-wrap items-center gap-1.5">
            <Badge variant={status.variant}>{status.label}</Badge>
            {email.category_id && (
              <Badge variant="outline">Category Inbox · {email.category_name || "Unknown"}</Badge>
            )}
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
        <ReminderStatusBar interactionId={email.interaction_id} />
      </div>

      {/* Fullscreen only — Sender Information pinned right below the
          header, alongside Subject/Date, instead of buried mid-scroll. */}
      {isFullscreen && <div className="border-b border-border px-5 py-4">{senderInfoSection}</div>}

      {/* Attachments / Tags / Message Body — the only scrolling region */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="flex flex-col gap-5">
          {!isFullscreen && senderInfoSection}

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
          </section>

          <section>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Message</h3>
            <div className="flex flex-col gap-3">
              {/* Newest reply first; the original message (and its composer slot) last. */}
              {newestFirst(email.replies).map((reply) => {
                const isMessageSelected = selectedMessageId === reply.interaction_id;
                const wrapperClassName = cn(
                  "rounded-lg transition-colors",
                  isMessageSelected && "-mx-1.5 p-1.5 bg-primary/5 ring-2 ring-primary/50"
                );
                if (reply.interaction_type === "FORWARD") {
                  return (
                    <div key={reply.interaction_id} id={`mail-message-${reply.interaction_id}`} className={wrapperClassName}>
                      <ForwardActionRow
                        data={forwardAction(reply)}
                        currentUserId={currentUser?.user_id}
                      />
                    </div>
                  );
                }
                const bubbleData = replyBubble(reply);
                return (
                  <Fragment key={reply.interaction_id}>
                    <div id={`mail-message-${reply.interaction_id}`} className={wrapperClassName}>
                      <Bubble
                        data={bubbleData}
                        canRetry={bubbleData.performedBy === currentUser?.user_id}
                        isRetrying={retryAction.isLoading}
                        onRetrySend={handleRetrySend}
                        canReplyExternal={canReplyExternal}
                        replyDisabled={isClosed || replyAccessCheck.isLoading}
                        onReply={() => handleReplyClick(bubbleData, "reply")}
                        onReplyAll={() => handleReplyClick(bubbleData, "replyAll")}
                        onForward={() => handleForwardClick(bubbleData)}
                      />
                    </div>
                    {renderReplyComposerFor(reply.interaction_id)}
                  </Fragment>
                );
              })}
              {/* Original message last — the thread reads newest to oldest. */}
              <div
                id={`mail-message-${email.interaction_id}`}
                className={cn(
                  "rounded-lg transition-colors",
                  selectedMessageId === email.interaction_id && "-mx-1.5 p-1.5 bg-primary/5 ring-2 ring-primary/50"
                )}
              >
                <Bubble
                  data={rootBubbleData}
                  canReplyExternal={canReplyExternal}
                  replyDisabled={isClosed || replyAccessCheck.isLoading}
                  onReply={() => handleReplyClick(rootBubbleData, "reply")}
                  onReplyAll={() => handleReplyClick(rootBubbleData, "replyAll")}
                  onForward={() => handleForwardClick(rootBubbleData)}
                />
              </div>
              {renderReplyComposerFor(email.interaction_id)}
            </div>
          </section>
        </div>
      </div>

      {/* Action Toolbar — pinned below the scrolling content, never scrolls out of view.
          Fullscreen already shows these same actions in its own top bar (see above). */}
      {!isFullscreen && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-muted/20 px-5 py-2.5">
          {toolbarActions}
        </div>
      )}

      {isClosed && (
        <div className="border-t border-border p-4 text-center text-[12px] text-muted-foreground">
          This ticket is closed — reopen it from the ticket page to reply.
        </div>
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
              <Select value={ticketType} onValueChange={setTicketType} disabled={allCategoriesLoading}>
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      allCategoriesLoading
                        ? "Loading categories…"
                        : allCategoriesError
                          ? "Failed to load categories"
                          : "Select"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {allCategories.map((c) => (
                    <SelectItem key={c.category_id} value={c.category_name}>
                      {c.category_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {allCategoriesError && (
                <p className="mt-1 text-xs text-destructive">
                  Couldn't load categories. Please try again or contact an admin.
                </p>
              )}
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
                    {canAssignTicket &&
                      assignableAgents?.groups.map((group) => (
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

                {canAssignTicket && (
                  <div className="mt-1">
                    <AdditionalAssignmentRows
                      categories={allCategories}
                      rows={additionalRows}
                      onChange={setAdditionalRows}
                      primaryUserId={resolvedAgentId}
                      defaultCategory={ticketType}
                    />
                    {additionalRowsNeedPrimary && (
                      <p className="mt-1 text-xs text-destructive">
                        Choose the primary assignee in “Assigned To” first.
                      </p>
                    )}
                  </div>
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
                additionalRowsNeedPrimary ||
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
    </TooltipProvider>
  );
}
