import type { NotificationItem } from "@/lib/notifications-api";

// "Mail" for the notification dropdown means exactly these two types — the
// "New mail from X" / "New reply from X" notifications, whose rendering must
// stay byte-for-byte unchanged. MAIL_FORWARDED/OTP_FORWARDED are deliberately
// excluded — they carry a full forwarded email body and are treated as
// "forwarded content" (body hidden) instead, per the dropdown's own hidden-
// content rules.
const MAIL_TYPES = new Set(["MAIL_RECEIVED", "CLIENT_REPLY"]);

export function isMailNotification(notification: NotificationItem): boolean {
  return MAIL_TYPES.has(notification.notification_type);
}

export interface NotificationDisplay {
  headline: string;
  fromLabel: string | null;
  showBody: boolean;
  bodyText?: string;
}

// The backend has no separate actor/ticket-subject fields on a notification
// (see unified-backend/app/notifications/schemas.py) — title/message are
// pre-formatted strings baked in at notify() call time. This formats what's
// already there per type, hiding large free-form bodies (internal note text,
// SLA email snippets, escalation paragraphs, forwarded mail) while leaving
// already-concise types (assignment/status/priority/resolved/permission)
// showing exactly what they show today.
export function formatNotificationForDropdown(notification: NotificationItem): NotificationDisplay {
  const { notification_type: type, title, message } = notification;

  switch (type) {
    case "INTERNAL_NOTE_ADDED": {
      // message = `${note}\n\nFrom: ${actor}\n(To: ${recipients})?` — see
      // interaction_service.py. Same shape SystemMailDetailsView.tsx's own
      // parseInternalNoteMessage() already parses; duplicated in miniature
      // here rather than imported, to avoid touching that unrelated file.
      const match = message.match(/\n\nFrom: (.+?)(?:\nTo: .+)?$/);
      return {
        headline: `Internal Note: ${title}`,
        fromLabel: match?.[1] ?? "a teammate",
        showBody: false,
      };
    }

    case "SLA_HALF_ELAPSED":
    case "SLA_AT_RISK":
    case "SLA_BREACHED":
    case "SLA_ESCALATED": {
      // First-response messages start with `From ${who}: "${subject}" is
      // still awaiting first response.` (sla_breach_notifier.py). Resolution
      // SLA messages have no leading "From" (sla_sweep_service.py) and
      // correctly fall back to "System".
      const match = message.match(/^From (.+?): "/);
      return { headline: title, fromLabel: match?.[1] ?? "System", showBody: false };
    }

    case "ESCALATION_CREATED":
    case "ESCALATION_ADVANCED": {
      // Manual escalations start with `${current_user.name} escalated/
      // advanced...` (escalation_service.py); auto-triggered ones don't open
      // with a person's name and correctly fall back to "System".
      const match = message.match(/^([A-Z][\w .'-]{1,60}?) (?:escalated|advanced|acknowledged)\b/);
      return { headline: title, fromLabel: match?.[1] ?? "System", showBody: false };
    }

    case "MAIL_FORWARDED":
    case "OTP_FORWARDED":
      return { headline: title, fromLabel: null, showBody: false };

    default:
      // TICKET_ASSIGNED, TICKET_STATUS_CHANGED, TICKET_PRIORITY_CHANGED,
      // TICKET_RESOLVED, PERMISSION_*, and any future/unrecognized type —
      // already concise, unchanged passthrough.
      return { headline: title, fromLabel: null, showBody: true, bodyText: message };
  }
}
