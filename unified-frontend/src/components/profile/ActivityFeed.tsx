"use client";

import { ArrowUpRight, History } from "lucide-react";

import { actionBadgeVariant, ActionIcon } from "@/components/shared/audit";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { AuditLog } from "@/types";

interface ActivityFeedProps {
  activity: AuditLog[];
  isLoading: boolean;
  isError: boolean;
  limit?: number;
  onViewAll?: () => void;
  title?: string;
  description?: string;
}

// Backs the right-column "Recent Activity" widget (limit=5, a "View All"
// button that switches to the Activity tab), the Activity tab's own full
// list (no limit), and the Security tab's "Login History" (activity
// pre-filtered to auth.* actions by the caller) — same
// auditService.getUserLogs data, same rendering, one place this list is
// drawn.
export function ActivityFeed({
  activity,
  isLoading,
  isError,
  limit,
  onViewAll,
  title = "Recent Activity",
  description = "A record of actions taken on your account.",
}: ActivityFeedProps) {
  const visible = limit ? activity.slice(0, limit) : activity;

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="h-4 w-4" />
            {title}
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        {onViewAll && activity.length > 0 && (
          <button
            type="button"
            onClick={onViewAll}
            className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            View all
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        )}
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState message="Failed to load activity history." />
        ) : visible.length === 0 ? (
          <EmptyState
            title="No activity yet"
            description="Actions taken on your account will appear here."
          />
        ) : (
          <ol className="relative space-y-5 border-l border-border pl-6">
            {visible.map((log) => (
              <li key={log.audit_log_id} className="relative">
                <span className="absolute -left-[29px] flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground">
                  <ActionIcon action={log.action} />
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={actionBadgeVariant(log.action)}>{log.action}</Badge>
                  <span className="text-sm text-muted-foreground">on {log.entity_type}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{formatDate(log.timestamp)}</p>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
