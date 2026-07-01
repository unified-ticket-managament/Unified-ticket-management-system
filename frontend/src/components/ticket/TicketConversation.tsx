import { EyeOff } from "lucide-react";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { useApiAction } from "@/hooks/useApiAction";
import { hideInteraction } from "@/api/interaction";
import { useWorkflowContext } from "@/context/WorkflowContext";
import { CONVERSATION_TYPES, metaFor, summarize } from "@/lib/interactionMeta";

interface TicketConversationProps {
  onChanged: () => void;
}

export function TicketConversation({ onChanged }: TicketConversationProps) {
  const { activeTicket, timeline } = useWorkflowContext();
  const conversation = timeline.filter((i) => CONVERSATION_TYPES.includes(i.interaction_type));

  const { run: runHide, isLoading: isHiding } = useApiAction(hideInteraction, {
    successMessage: "Interaction hidden.",
  });

  async function handleHide(interactionId: string) {
    if (!activeTicket) return;
    const result = await runHide(activeTicket.ticket_id, interactionId, { removed_by: null });
    if (result) onChanged();
  }

  return (
    <Card title="Conversation" eyebrow={`${conversation.length} message${conversation.length === 1 ? "" : "s"}`}>
      {conversation.length === 0 ? (
        <EmptyState
          icon="💬"
          title="No conversation yet"
          description="Emails, replies, notes and attachments will appear here."
        />
      ) : (
        <ul className="flex flex-col gap-4">
          {conversation.map((item) => {
            const meta = metaFor(item.interaction_type);
            const isOutbound = item.direction === "OUTBOUND";
            const isInternal = item.direction === "INTERNAL";
            return (
              <li key={item.interaction_id} className="flex gap-3">
                <div
                  className={`flex h-9 w-9 flex-none items-center justify-center rounded-full border text-sm ${
                    isOutbound
                      ? "border-accent/20 bg-accent/10"
                      : isInternal
                      ? "border-warning/20 bg-warning/10"
                      : "border-border bg-canvas"
                  }`}
                >
                  {meta.icon}
                </div>
                <div
                  className={`group flex-1 rounded-md2 border p-4 transition-colors ${
                    isOutbound
                      ? "border-accent/15 bg-accent/5"
                      : isInternal
                      ? "border-warning/15 bg-warning/5"
                      : "border-border bg-canvas/60"
                  } ${!item.is_visible ? "opacity-40" : ""}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
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
                  {item.is_visible && (
                    <button
                      disabled={isHiding}
                      onClick={() => handleHide(item.interaction_id)}
                      aria-label="Hide this interaction"
                      className="mt-2.5 flex items-center gap-1 rounded-md2 text-[11px] font-medium text-muted opacity-0 transition-opacity hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30 disabled:opacity-50 group-hover:opacity-100"
                    >
                      <EyeOff size={12} /> Hide
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
