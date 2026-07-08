import { Avatar } from "@tw/components/common/Avatar";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import { formatDateTime } from "@tw/lib/format";
import type { AttachmentMeta } from "@tw/types";

export interface MessageCardData {
  key: string;
  senderName: string;
  senderEmail?: string | null;
  toLabel?: string | null;
  timestamp: string;
  body: string;
  isClientMessage: boolean;
  attachments?: AttachmentMeta[];
}

/**
 * One message in a mail thread — the root email and every reply
 * rendered through the exact same card shape (avatar, sender, "To:",
 * timestamp, body), so a conversation reads as one continuous
 * exchange instead of "one big root block, then differently-styled
 * reply bubbles" like this used to look. Client messages and agent
 * replies are told apart by avatar/label color only (both tones from
 * the same tone vocabulary Badge/StatusBadge already use elsewhere),
 * not by left/right alignment — full-width cards throughout, matching
 * the reference thread UI this was modeled on.
 */
export function MessageCard({ data }: { data: MessageCardData }) {
  const { senderName, senderEmail, toLabel, timestamp, body, isClientMessage, attachments } = data;

  return (
    <div className="rounded-md2 border border-border bg-surface px-4 py-3.5 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <Avatar name={senderName} size="sm" tone={isClientMessage ? "info" : "accent"} />
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-slate-900">
              {senderName}
              {senderEmail && (
                <span className="ml-1.5 font-normal text-muted">({senderEmail})</span>
              )}
            </p>
            {toLabel && <p className="text-[11px] text-muted">To: {toLabel}</p>}
          </div>
        </div>
        <span className="flex-none text-[11px] text-muted">{formatDateTime(timestamp)}</span>
      </div>

      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{body}</p>

      {attachments && attachments.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <AttachmentList attachments={attachments} />
        </div>
      )}
    </div>
  );
}
