"use client";

import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Bell, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@tw/lib/format";
import { linkifyPlainText } from "@tw/lib/richText";
import type { NotificationItem } from "@tw/types";

interface SystemMailDetailsViewProps {
  notification: NotificationItem;
  onBack: () => void;
  onMarkRead: (notificationId: string) => Promise<unknown>;
}

// A deliberately narrower sibling of MessageDetailsView — a system
// notice has no reply/forward/attachments/ticket-action toolbar, no
// thread, and isn't tied to a real Interaction, so this only ever
// renders Subject/From/Body/date plus a single "View Ticket" link (via
// the notification's own `link` field) and Back. Auto-marks the
// notification read on open, same as opening an email thread already
// implicitly marks it "opened" elsewhere in this Mail page.
export function SystemMailDetailsView({
  notification,
  onBack,
  onMarkRead,
}: SystemMailDetailsViewProps) {
  useEffect(() => {
    if (!notification.is_read) {
      onMarkRead(notification.notification_id);
    }
    // Only re-run when the open notification itself changes — marking
    // read must not re-fire just because onMarkRead's identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notification.notification_id]);

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-6 shadow-card">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-primary/10 text-primary">
            <Bell className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-[17px] font-semibold text-foreground">{notification.title}</h1>
            <p className="mt-1 text-[13px] text-muted-foreground">
              From: <span className="font-medium text-foreground/80">System</span>
            </p>
          </div>
        </div>
        <Badge variant="secondary" className="flex-none text-[11px]">
          {formatDateTime(notification.created_at)}
        </Badge>
      </div>

      <div
        className="text-[14px] leading-relaxed text-foreground/90"
        dangerouslySetInnerHTML={{ __html: linkifyPlainText(notification.message) }}
      />

      <div className="mt-2 flex items-center gap-2 border-t border-border pt-4">
        {notification.link && (
          <Button asChild size="sm" variant="ghost" className="gap-1.5 text-primary">
            <Link to={notification.link}>
              View Ticket
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
