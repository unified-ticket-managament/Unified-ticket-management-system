"use client";

import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Bell, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@tw/lib/format";
import { linkifyPlainText } from "@tw/lib/richText";
import type { NotificationItem } from "@tw/types";

interface SystemMailDetailsViewProps {
  notification: NotificationItem;
  onBack: () => void;
  onMarkRead: (notificationId: string) => Promise<unknown>;
  // See MessageDetailsView's identical prop for the full rationale —
  // "panel" drops this component's own card chrome when it renders
  // inside the Mail workspace's own already-chromed panel.
  variant?: "standalone" | "panel";
}

interface ParsedInternalNote {
  body: string;
  senderName: string;
  recipientNames: string[];
}

// InteractionService.add_internal_note (backend) writes an
// INTERNAL_NOTE_ADDED notification's `message` as
// "<full note body>\n\nFrom: <sender>[\nTo: <recipients>]" — there's
// no dedicated sender/recipient column on Notification, so this is
// the one place that format is parsed back apart, purely for display.
// Returns null for anything that doesn't match (e.g. a notification
// created before this format existed), which callers treat as "show
// the raw message, no sender/recipient line" — the same safe-degrade
// convention this codebase already uses for a stale/older JWT claim.
const INTERNAL_NOTE_MESSAGE_PATTERN = /^([\s\S]*)\n\nFrom: (.+?)(?:\nTo: (.+))?$/;

function parseInternalNoteMessage(message: string): ParsedInternalNote | null {
  const match = message.match(INTERNAL_NOTE_MESSAGE_PATTERN);
  if (!match) return null;
  const [, body, senderName, recipientsRaw] = match;
  return {
    body,
    senderName: senderName.trim(),
    recipientNames: recipientsRaw
      ? recipientsRaw
          .split(",")
          .map((name) => name.trim())
          .filter(Boolean)
      : [],
  };
}

// A deliberately narrower sibling of MessageDetailsView — a system
// notice has no reply/forward/attachments/ticket-action toolbar, no
// thread, and isn't tied to a real Interaction, so this only ever
// renders Subject/From/Body/date plus a single action link (via the
// notification's own `link` field) and Back. Auto-marks the
// notification read on open, same as opening an email thread already
// implicitly marks it "opened" elsewhere in this Mail page.
export function SystemMailDetailsView({
  notification,
  onBack,
  onMarkRead,
  variant = "standalone",
}: SystemMailDetailsViewProps) {
  // First Response SLA notifications (and MAIL_RECEIVED) point at a
  // still-pending email — `link` is an /inbox?interaction_id=... deep
  // link, not a ticket, so the action should read "View Mail". Every
  // other notification type (Resolution SLA, escalation, edit-access)
  // is `related_entity_type === "ticket"` and genuinely opens a ticket.
  const isMailLink = notification.related_entity_type === "interaction";
  const actionLabel = isMailLink ? "View Mail" : "View Ticket";

  // Only an INTERNAL_NOTE_ADDED notification's message is ever
  // written in the "<body>\n\nFrom: ...\nTo: ..." shape
  // parseInternalNoteMessage expects — every other type keeps
  // rendering notification.message verbatim, unaffected.
  const internalNote =
    notification.notification_type === "INTERNAL_NOTE_ADDED"
      ? parseInternalNoteMessage(notification.message)
      : null;
  const senderLabel = internalNote?.senderName ?? "System";
  const bodyText = internalNote?.body ?? notification.message;

  useEffect(() => {
    if (!notification.is_read) {
      onMarkRead(notification.notification_id);
    }
    // Only re-run when the open notification itself changes — marking
    // read must not re-fire just because onMarkRead's identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notification.notification_id]);

  return (
    <div
      className={cn(
        "flex flex-col gap-4 p-6",
        variant !== "panel" && "rounded-xl border border-border bg-card shadow-card"
      )}
    >
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-primary/10 text-primary">
            <Bell className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="break-words text-[17px] font-semibold text-foreground">
              {notification.title}
            </h1>
            <p className="mt-1 text-[13px] text-muted-foreground">
              From: <span className="font-medium text-foreground/80">{senderLabel}</span>
            </p>
            {internalNote && internalNote.recipientNames.length > 0 && (
              <p className="mt-0.5 text-[13px] text-muted-foreground">
                To:{" "}
                <span className="font-medium text-foreground/80">
                  {internalNote.recipientNames.join(", ")}
                </span>
              </p>
            )}
          </div>
        </div>
        <Badge variant="secondary" className="flex-none text-[11px]">
          {formatDateTime(notification.created_at)}
        </Badge>
      </div>

      <div
        className="whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground/90 [&_a]:break-all"
        dangerouslySetInnerHTML={{ __html: linkifyPlainText(bodyText) }}
      />

      <div className="mt-2 flex items-center gap-2 border-t border-border pt-4">
        {notification.link && (
          <Button asChild size="sm" variant="ghost" className="gap-1.5 text-primary">
            <Link to={notification.link}>
              {actionLabel}
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </Button>
        )}
        <Button size="sm" variant="ghost" className="ml-auto gap-1.5" onClick={onBack}>
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Message List
        </Button>
      </div>
    </div>
  );
}
