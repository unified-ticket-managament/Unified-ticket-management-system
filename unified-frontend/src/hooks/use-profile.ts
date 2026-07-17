"use client";

import { useQuery } from "@tanstack/react-query";

import { auditService, categoryService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useProfileExtrasStore } from "@/store/profile-extras-store";
import { useSettingsStore } from "@/store/settings-store";
import { Category, User } from "@/types";
import { getDashboardStats } from "@tw/api/ticket";
import { useDashboardSlaCounts } from "@tw/hooks/useDashboardSlaCounts";

// Composes every data source the Profile page needs (RBAC user record,
// resolved category/manager/teamlead names, audit-log activity, and the
// same live ticket-workspace endpoints the Dashboard already uses) into
// one place, rather than the previous page's ad hoc inline useQuerys.
export function useProfileData() {
  const user = useAuthStore((s) => s.user);
  const extras = useProfileExtrasStore();
  const language = useSettingsStore((s) => s.language);
  const notifications = useSettingsStore((s) => s.notifications);
  const security = useSettingsStore((s) => s.security);

  const userRecordQuery = useQuery({
    queryKey: ["profile-full-record", user?.user_id],
    queryFn: async () => (await userService.get(user!.user_id)) as User,
    enabled: !!user?.user_id,
  });
  const record = userRecordQuery.data;

  const categoryQuery = useQuery({
    queryKey: ["profile-category", record?.category_id],
    queryFn: async () => (await categoryService.get(record!.category_id as string)) as Category,
    enabled: !!record?.category_id,
  });

  const managerQuery = useQuery({
    queryKey: ["profile-manager", record?.manager_id],
    queryFn: async () => (await userService.get(record!.manager_id as string)) as User,
    enabled: !!record?.manager_id,
  });

  const teamleadQuery = useQuery({
    queryKey: ["profile-teamlead", record?.teamlead_id],
    queryFn: async () => (await userService.get(record!.teamlead_id as string)) as User,
    enabled: !!record?.teamlead_id,
  });

  const activityQuery = useQuery({
    queryKey: ["user-activity", user?.user_id],
    queryFn: () => auditService.getUserLogs(user!.user_id),
    enabled: !!user?.user_id,
  });

  const dashboardStatsQuery = useQuery({
    queryKey: ["profile-dashboard-stats"],
    queryFn: () => getDashboardStats(),
    enabled: !!user?.user_id,
  });

  const { counts: slaCounts, isLoading: slaLoading } = useDashboardSlaCounts();

  const activity = activityQuery.data ?? [];
  const lastLogin = activity.find((log) => log.action === "auth.login") ?? null;

  const slaTotal =
    slaCounts.running +
    slaCounts.paused +
    slaCounts.atRisk +
    slaCounts.breached +
    slaCounts.escalated +
    slaCounts.completed;
  const slaCompliancePct =
    slaTotal > 0
      ? Math.round(((slaTotal - slaCounts.breached - slaCounts.escalated) / slaTotal) * 100)
      : null;

  const departmentName = categoryQuery.data?.category_name ?? null;
  const reportsToName = managerQuery.data?.name ?? teamleadQuery.data?.name ?? null;
  const teamName = departmentName ? `${departmentName} Team` : null;

  return {
    user,
    record,
    extras,
    language,
    notifications,
    security,
    departmentName,
    reportsToName,
    teamName,
    joinedDate: record?.created_at ?? null,
    activity,
    activityLoading: activityQuery.isLoading,
    activityError: activityQuery.isError,
    lastLogin: lastLogin?.timestamp ?? null,
    dashboardStats: dashboardStatsQuery.data ?? null,
    dashboardStatsLoading: dashboardStatsQuery.isLoading,
    slaCompliancePct,
    slaLoading,
  };
}
