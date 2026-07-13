import { EyeOff } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { EmptyState } from "@tw/components/common/EmptyState";
import { AttachmentList } from "@tw/components/common/AttachmentList";
import { RETIRED_INTERACTION_TYPES, metaFor, summarize } from "@tw/lib/interactionMeta";
import { shortId } from "@tw/lib/format";
import type { InteractionResponse } from "@tw/types";

const toneRing: Record<string, string> = {
  default: "border-slate-200 bg-slate-50",
  success: "border-success/25 bg-success/10",
  warning: "border-warning/25 bg-warning/10",
  danger: "border-danger/25 bg-danger/10",
  info: "border-info/25 bg-info/10",
  accent: "border-accent/25 bg-accent/10",
};

const toneCard: Record<string, string> = {
  default: "border-border bg-canvas/60",
  success: "border-success/15 bg-success/5",
  warning: "border-warning/15 bg-warning/5",
  danger: "border-danger/15 bg-danger/5",
  info: "border-info/15 bg-info/5",
  accent: "border-accent/15 bg-accent/5",
};

interface TicketConversationFeedProps {
  events: InteractionResponse[];
  // All optional — the Timeline tab passes these to offer the
  // existing "Hide" soft-delete action and click-to-open-details-
  // drawer behavior; the full-page Ticket Interaction view (read-only
  // conversation history) omits them.
  onHide?: (interactionId: string) => void;
  isHiding?: boolean;
  onItemClick?: (item: InteractionResponse) => void;
}

// Shared chronological activity feed — every incoming email, outgoing
// reply, internal note, status/priority change, and attachment upload
// on a ticket, rendered identically whether it's embedded in the
// Timeline tab or shown full-page on the Ticket Interaction view (see
// TicketTimeline.tsx and pages/TicketInteractionPage.tsx).
export function TicketConversationFeed({
  events,
  onHide,
  isHiding = false,
  onItemClick,
}: TicketConversationFeedProps) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon="🕒"
        title="No activity yet"
        description="Emails, replies, notes, status changes and uploads will appear here as they happen."
      />
    );
  }

  return (
    <ol className="flex flex-col gap-0">
      {events.map((item, index) => {
        const meta = metaFor(item.interaction_type);
        const isLast = index === events.length - 1;

        return (
          <li key={item.interaction_id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-8 w-8 flex-none items-center justify-center rounded-full border text-sm ${toneRing[meta.tone]}`}
              >
                {meta.icon}
              </div>
              {!isLast && <div className="w-px flex-1 bg-border" />}
            </div>

            <div
              role={onItemClick ? "button" : undefined}
              tabIndex={onItemClick ? 0 : undefined}
              onClick={onItemClick ? () => onItemClick(item) : undefined}
              onKeyDown={
                onItemClick
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") onItemClick(item);
                    }
                  : undefined
              }
              className={`group flex-1 rounded-md2 border p-4 pb-5 transition-colors ${
                onItemClick ? "cursor-pointer hover:bg-surfaceHover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40" : ""
              } ${toneCard[meta.tone]} ${!item.is_visible ? "opacity-40" : ""}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[13px] font-semibold text-slate-900">{meta.label}</p>
                  <Badge tone={meta.tone}>{item.direction}</Badge>
                  {!item.is_visible && <Badge tone="danger">hidden</Badge>}
                </div>
                <p className="text-[11px] font-medium text-muted">
                  {new Date(item.created_at).toLocaleString()}
                </p>
              </div>

              <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700">
                {summarize(item)}
              </p>

              {item.attachments && item.attachments.length > 0 && (
                <AttachmentList attachments={item.attachments} className="mt-2.5" />
              )}

              <div className="mt-2.5 flex items-center justify-between gap-2">
                <p className="text-[11px] text-muted">
                  {item.performed_by
                    ? `Performed by ${item.performed_by_name ?? shortId(item.performed_by)}`
                    : ""}
                </p>
                {onHide && item.is_visible && !RETIRED_INTERACTION_TYPES.has(item.interaction_type) && (
                  <button
                    disabled={isHiding}
                    onClick={(e) => {
                      e.stopPropagation();
                      onHide(item.interaction_id);
                    }}
                    aria-label="Hide this interaction"
                    className="flex items-center gap-1 rounded-md2 text-[11px] font-medium text-muted opacity-0 transition-opacity hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30 disabled:opacity-50 group-hover:opacity-100"
                  >
                    <EyeOff size={12} /> Hide
                  </button>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
