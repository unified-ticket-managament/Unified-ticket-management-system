"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ClipboardList,
  FolderKanban,
  KeyRound,
  ListChecks,
  Settings as SettingsIcon,
  Shield,
  ShieldPlus,
  UserCircle,
  UserPlus,
  Users,
} from "lucide-react";
import { useMemo } from "react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { actionBadgeVariant, ActionIcon } from "@/components/shared/audit";
import { AreaTrendChart, CategoryBarList } from "@/components/shared/charts";
import { EmptyState, StatCard } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useTranslation } from "@/hooks/use-translation";
import { ROLE_NAMES } from "@/lib/role-access";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { auditService, permissionService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { AuditLog, Role, User } from "@/types";

const WEEKLY_LOGIN_ACTIVITY = [
  { label: "Mon", value: 38 },
  { label: "Tue", value: 52 },
  { label: "Wed", value: 47 },
  { label: "Thu", value: 61 },
  { label: "Fri", value: 55 },
  { label: "Sat", value: 21 },
  { label: "Sun", value: 17 },
];

export default function DashboardPage() {
  const currentUser = useAuthStore((state) => state.user);
  const hasAnyPermission = useAuthStore((state) => state.hasAnyPermission);
  const { t } = useTranslation();
  const role = currentUser?.role;

  const QUICK_ACTIONS = useMemo(
    () => [
      {
        title: t("dashboard.addUser"),
        description: t("dashboard.addUserDesc"),
        href: "/users",
        icon: UserPlus,
        permission: "user:create",
      },
      {
        title: t("dashboard.createRole"),
        description: t("dashboard.createRoleDesc"),
        href: "/roles",
        icon: ShieldPlus,
        permission: "role:create",
      },
      {
        title: t("dashboard.viewAuditLogs"),
        description: t("dashboard.viewAuditLogsDesc"),
        href: "/audit-logs",
        icon: ClipboardList,
        permission: "audit:view",
      },
    ],
    [t]
  );

  const canSeeUsers =
    role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.MANAGER || role === ROLE_NAMES.TEAM_LEAD;
  const canSeeRoles = role === ROLE_NAMES.SUPER_ADMIN || role === ROLE_NAMES.MANAGER;
  const canSeePermissions = role === ROLE_NAMES.SUPER_ADMIN;
  const canSeeAuditLogs = role === ROLE_NAMES.SUPER_ADMIN;
  const canSeeCharts = role === ROLE_NAMES.SUPER_ADMIN;
  const isStaff = role === ROLE_NAMES.STAFF;
  const isViewer = role === ROLE_NAMES.VIEWER;
  const hasAdminQuickActions = hasAnyPermission(QUICK_ACTIONS.map((a) => a.permission));

  const usersQuery = useQuery({
    queryKey: ["dashboard-users"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
    enabled: canSeeUsers,
  });

  const rolesQuery = useQuery({
    queryKey: ["dashboard-roles"],
    queryFn: () => roleService.list(),
    enabled: canSeeRoles,
  });

  const permissionsQuery = useQuery({
    queryKey: ["dashboard-permissions"],
    queryFn: () => permissionService.list(),
    enabled: canSeePermissions,
  });

  const auditQuery = useQuery({
    queryKey: ["dashboard-audit-logs"],
    queryFn: () => auditService.list({ page: 1, page_size: 8 }),
  });

  const roleMap = useMemo(() => {
    const map = new Map<string, string>();
    (rolesQuery.data?.roles ?? []).forEach((r: Role) => map.set(r.role_id, r.name));
    return map;
  }, [rolesQuery.data]);

  const usersByRole = useMemo(() => {
    const users: User[] = usersQuery.data?.users ?? [];
    if (users.length === 0) return [];

    const counts = new Map<string, number>();
    users.forEach((user) => {
      const roleName = roleMap.get(user.role_id) ?? "Unassigned";
      counts.set(roleName, (counts.get(roleName) ?? 0) + 1);
    });

    return Array.from(counts.entries())
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 6);
  }, [usersQuery.data, roleMap]);

  const recentUsers = useMemo(() => {
    const users: User[] = usersQuery.data?.users ?? [];
    return [...users]
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 5);
  }, [usersQuery.data]);

  const recentLogs: AuditLog[] = auditQuery.data?.logs ?? [];

  const statCards = useMemo(() => {
    const cards: { title: string; value: string | number; subtitle: string; icon: typeof Users }[] = [];

    if (canSeeUsers) {
      cards.push({
        title: t("dashboard.totalUsers"),
        value: usersQuery.data?.total ?? (usersQuery.isLoading ? "…" : 0),
        subtitle: "Across all roles",
        icon: Users,
      });
    }
    if (canSeeRoles) {
      cards.push({
        title: t("dashboard.totalRoles"),
        value: rolesQuery.data?.total ?? (rolesQuery.isLoading ? "…" : 0),
        subtitle: "Configured access roles",
        icon: Shield,
      });
    }
    if (canSeePermissions) {
      cards.push({
        title: t("dashboard.totalPermissions"),
        value: permissionsQuery.data?.total ?? (permissionsQuery.isLoading ? "…" : 0),
        subtitle: "Granular capabilities",
        icon: KeyRound,
      });
    }
    if (canSeeAuditLogs) {
      cards.push({
        title: t("dashboard.auditLogsStat"),
        value: auditQuery.data?.total ?? (auditQuery.isLoading ? "…" : 0),
        subtitle: "Recorded system events",
        icon: ClipboardList,
      });
    }
    if (isStaff) {
      cards.push({
        title: t("dashboard.tasks"),
        value: 12,
        subtitle: "Mock — assigned to you",
        icon: ListChecks,
      });
      cards.push({
        title: t("dashboard.projects"),
        value: 4,
        subtitle: "Mock — active projects",
        icon: FolderKanban,
      });
    }

    return cards;
  }, [
    t,
    canSeeUsers,
    canSeeRoles,
    canSeePermissions,
    canSeeAuditLogs,
    isStaff,
    usersQuery.data,
    usersQuery.isLoading,
    rolesQuery.data,
    rolesQuery.isLoading,
    permissionsQuery.data,
    permissionsQuery.isLoading,
    auditQuery.data,
    auditQuery.isLoading,
  ]);

  const personalLinks = useMemo(() => {
    const links = [
      { title: t("dashboard.viewProfile"), description: t("dashboard.viewProfileDesc"), href: "/profile", icon: UserCircle },
      { title: t("nav.settings"), description: t("dashboard.settingsDesc"), href: "/settings", icon: SettingsIcon },
    ];
    if (canSeeUsers) {
      links.unshift({ title: t("dashboard.viewUsers"), description: t("dashboard.viewUsersDesc"), href: "/users", icon: Users });
    }
    return links;
  }, [canSeeUsers, t]);

  const secondaryActionsTitle = isViewer ? t("dashboard.quickLinks") : t("dashboard.quickActions");

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("dashboard.welcome", { name: currentUser?.name ?? "there" })}
        description={t("dashboard.subtitle")}
      />

      {/* Statistics Cards */}
      {statCards.length > 0 && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {statCards.map((card) => (
            <StatCard
              key={card.title}
              title={card.title}
              value={card.value}
              subtitle={card.subtitle}
              icon={card.icon}
            />
          ))}
        </div>
      )}

      {/* Profile Summary (Viewer) */}
      {isViewer && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("dashboard.profileSummary")}</CardTitle>
            <CardDescription>Your account at a glance.</CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-4">
            <Avatar className="h-14 w-14">
              <AvatarFallback className="text-lg">
                {currentUser?.name?.charAt(0).toUpperCase() ?? "U"}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="font-semibold">{currentUser?.name}</p>
              <p className="truncate text-sm text-muted-foreground">{currentUser?.email}</p>
              <Badge variant="secondary" className="mt-1">
                {currentUser?.role}
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quick Actions / Quick Links */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">{secondaryActionsTitle}</h2>
        {hasAdminQuickActions ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {QUICK_ACTIONS.map((action) => {
              const Icon = action.icon;
              return (
                <PermissionGuard key={action.href} permission={action.permission}>
                  <Link href={action.href}>
                    <Card className="group h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-md">
                      <CardContent className="flex items-start gap-3 p-5">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                          <Icon className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium">{action.title}</p>
                          <p className="mt-0.5 text-xs text-muted-foreground">{action.description}</p>
                        </div>
                      </CardContent>
                    </Card>
                  </Link>
                </PermissionGuard>
              );
            })}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {personalLinks.map((link) => {
              const Icon = link.icon;
              return (
                <Link key={link.href} href={link.href}>
                  <Card className="group h-full cursor-pointer transition-all hover:-translate-y-0.5 hover:shadow-md">
                    <CardContent className="flex items-start gap-3 p-5">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium">{link.title}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">{link.description}</p>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* Charts (Super Admin only) */}
      {canSeeCharts && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("dashboard.weeklyLoginActivity")}</CardTitle>
              <CardDescription>Mock data — logins recorded per day</CardDescription>
            </CardHeader>
            <CardContent>
              <AreaTrendChart data={WEEKLY_LOGIN_ACTIVITY} valueFormatter={(v) => `${v} logins`} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("dashboard.usersByRole")}</CardTitle>
              <CardDescription>Current distribution across roles</CardDescription>
            </CardHeader>
            <CardContent>
              {usersQuery.isLoading ? (
                <div className="space-y-4">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-6 w-full" />
                  ))}
                </div>
              ) : usersByRole.length === 0 ? (
                <EmptyState title="No users yet" description="Users will appear here once created." />
              ) : (
                <CategoryBarList data={usersByRole} />
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Recent Users + Recent Activity */}
      <div className={cn("grid gap-6", canSeeUsers && "lg:grid-cols-2")}>
        {canSeeUsers && (
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="text-base">{t("dashboard.recentUsers")}</CardTitle>
                <CardDescription>Newest members of your organization</CardDescription>
              </div>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/users" className="gap-1 text-xs">
                  {t("dashboard.viewAll")}
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-1">
              {usersQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))
              ) : recentUsers.length === 0 ? (
                <EmptyState title="No users yet" description="New users will show up here." />
              ) : (
                recentUsers.map((user) => (
                  <div
                    key={user.user_id}
                    className="flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50"
                  >
                    <Avatar className="h-9 w-9">
                      <AvatarFallback>{user.name.charAt(0).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{user.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                    </div>
                    <Badge variant="secondary" className="shrink-0">
                      {roleMap.get(user.role_id) ?? "—"}
                    </Badge>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {role === ROLE_NAMES.SUPER_ADMIN ? t("dashboard.recentActivities") : t("dashboard.recentActivity")}
            </CardTitle>
            <CardDescription>Latest actions across the platform</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1">
            {auditQuery.isLoading ? (
              Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)
            ) : recentLogs.length === 0 ? (
              <EmptyState title="No activity yet" description="Actions will be logged here." />
            ) : (
              recentLogs.slice(0, 5).map((log) => (
                <div key={log.audit_log_id} className="flex items-start gap-3 rounded-lg px-2 py-2.5">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <ActionIcon action={log.action} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">
                      <span className="font-medium">{log.action}</span>{" "}
                      <span className="text-muted-foreground">on {log.entity_type}</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatRelativeTime(log.timestamp)}
                    </p>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {/* Latest Audit Logs (Super Admin only) */}
      {canSeeAuditLogs && (
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="text-base">{t("dashboard.latestAuditLogs")}</CardTitle>
              <CardDescription>Detailed record of recent system events</CardDescription>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/audit-logs" className="gap-1 text-xs">
                {t("dashboard.viewAll")}
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            {auditQuery.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : recentLogs.length === 0 ? (
              <EmptyState title="No audit logs yet" description="System activity will appear here." />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Action</TableHead>
                    <TableHead>Entity</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Timestamp</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recentLogs.map((log) => (
                    <TableRow key={log.audit_log_id}>
                      <TableCell className="font-medium">{log.action}</TableCell>
                      <TableCell className="text-muted-foreground">{log.entity_type}</TableCell>
                      <TableCell>
                        <Badge variant={actionBadgeVariant(log.action)}>{log.action}</Badge>
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {formatDate(log.timestamp)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
