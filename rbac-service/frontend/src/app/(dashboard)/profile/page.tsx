"use client";

import { useQuery } from "@tanstack/react-query";
import { Network } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { OrganizationModal } from "@/components/organization/OrganizationModal";
import { actionBadgeVariant, ActionIcon } from "@/components/shared/audit";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/hooks/use-translation";
import { formatDate } from "@/lib/utils";
import { auditService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useProfileExtrasStore } from "@/store/profile-extras-store";

export default function ProfilePage() {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const [orgChartOpen, setOrgChartOpen] = useState(false);
  const { phone, address, avatarUrl } = useProfileExtrasStore();

  const userRecordQuery = useQuery({
    queryKey: ["profile-full-record", user?.user_id],
    queryFn: () => userService.get(user!.user_id),
    enabled: !!user?.user_id,
  });

  const activityQuery = useQuery({
    queryKey: ["user-activity", user?.user_id],
    queryFn: () => auditService.getUserLogs(user!.user_id),
    enabled: !!user?.user_id,
  });

  const activity = activityQuery.data ?? [];

  const fields = [
    { label: t("profile.email"), value: user?.email },
    { label: t("profile.role"), value: user?.role },
    { label: t("profile.phone"), value: phone || t("profile.notSet") },
    { label: t("profile.department"), value: t("profile.notSet") },
    {
      label: t("profile.joinedDate"),
      value: userRecordQuery.data?.created_at ? formatDate(userRecordQuery.data.created_at) : "—",
    },
  ];

  return (
    <div>
      <PageHeader title={t("profile.title")} description={t("profile.description")} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Account Details</CardTitle>
            <CardDescription>Your profile is read-only. Edit it from Settings.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex items-center gap-4">
              <Avatar className="h-16 w-16">
                {avatarUrl && <AvatarImage src={avatarUrl} alt={user?.name ?? "Avatar"} />}
                <AvatarFallback className="text-xl">
                  {user?.name?.charAt(0).toUpperCase() ?? "U"}
                </AvatarFallback>
              </Avatar>
              <div>
                <p className="font-semibold">{user?.name}</p>
                <Badge className="mt-1">{user?.role}</Badge>
              </div>
            </div>

            <dl className="grid gap-4 sm:grid-cols-2">
              {fields.map((field) => (
                <div key={field.label}>
                  <dt className="text-sm text-muted-foreground">{field.label}</dt>
                  <dd className="mt-0.5 text-sm font-medium">{field.value}</dd>
                </div>
              ))}
              <div>
                <dt className="text-sm text-muted-foreground">{t("profile.address")}</dt>
                <dd className="mt-0.5 text-sm font-medium">{address || t("profile.notSet")}</dd>
              </div>
            </dl>

            <Button
              variant="outline"
              className="gap-2"
              onClick={() => setOrgChartOpen(true)}
            >
              <Network className="h-4 w-4" />
              {t("profile.orgChart")}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Activity Timeline</CardTitle>
            <CardDescription>A record of actions taken on your account.</CardDescription>
          </CardHeader>
          <CardContent>
            {activityQuery.isLoading ? (
              <div className="space-y-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : activityQuery.isError ? (
              <ErrorState message="Failed to load activity history." />
            ) : activity.length === 0 ? (
              <EmptyState
                title="No activity yet"
                description="Actions taken on your account will appear here."
              />
            ) : (
              <ol className="relative space-y-6 border-l border-border pl-6">
                {activity.map((log) => (
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
      </div>

      <OrganizationModal open={orgChartOpen} onOpenChange={setOrgChartOpen} />
    </div>
  );
}
