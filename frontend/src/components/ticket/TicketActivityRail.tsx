import { Link, useParams } from "react-router-dom";
import { Card } from "@/components/common/Card";
import { EmptyState } from "@/components/common/EmptyState";
import { ACTIVITY_TYPES, metaFor, summarize } from "@/lib/interactionMeta";
import { useWorkflowContext } from "@/context/WorkflowContext";

const toneRing: Record<string, string> = {
  default: "border-slate-200 bg-slate-50",
  success: "border-success/25 bg-success/10",
  warning: "border-warning/25 bg-warning/10",
  danger: "border-danger/25 bg-danger/10",
  info: "border-info/25 bg-info/10",
  accent: "border-accent/25 bg-accent/10",
};

export function TicketActivityRail() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const { timeline } = useWorkflowContext();
  const activity = timeline.filter((i) => ACTIVITY_TYPES.includes(i.interaction_type));

  return (
    <Card
      title="Activity"
      eyebrow="Timeline"
      actions={
        ticketId && (
          <Link
            to={`/interactions?ticketId=${ticketId}`}
            className="text-[11px] font-semibold text-accent transition-colors hover:text-accent-700"
          >
            View all
          </Link>
        )
      }
    >
      {activity.length === 0 ? (
        <EmptyState
          icon="🕒"
          title="No activity yet"
          description="Status and priority changes will appear here."
        />
      ) : (
        <ol className="flex flex-col gap-0">
          {activity.map((item, index) => {
            const meta = metaFor(item.interaction_type);
            const isLast = index === activity.length - 1;
            return (
              <li key={item.interaction_id} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={`flex h-7 w-7 flex-none items-center justify-center rounded-full border text-xs ${toneRing[meta.tone]}`}
                  >
                    {meta.icon}
                  </div>
                  {!isLast && <div className="w-px flex-1 bg-border" />}
                </div>
                <div className="flex-1 pb-5">
                  <p className="text-[12px] font-semibold text-slate-900">{meta.label}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{summarize(item)}</p>
                  <p className="mt-1 text-[10px] font-medium text-muted">
                    {new Date(item.created_at).toLocaleString()}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
