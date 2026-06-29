"use client";

import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Shield, Users, ClipboardList } from "lucide-react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { StatCard } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { auditService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);

  const usersQuery = useQuery({
    queryKey: ["users", "stats"],
    queryFn: () => userService.list({ page: 1, page_size: 1 }),
    enabled: user?.permissions.includes("user:view") ?? false,
  });

  const auditQuery = useQuery({
    queryKey: ["audit", "stats"],
    queryFn: () => auditService.list({ page: 1, page_size: 5 }),
    enabled: user?.permissions.includes("audit:view") ?? false,
  });

  return (
    <div>
      <PageHeader
        title={`Welcome, ${user?.name}`}
        description="Role-aware dashboard with permission-based visibility"
      />

      <div className="grid gap-6 md:grid-cols-3">
        <StatCard title="Your Role" value={user?.role || "-"} subtitle="Current access level" />
        <PermissionGuard permission="user:view">
          <StatCard
            title="Total Users"
            value={usersQuery.isLoading ? "..." : usersQuery.data?.total ?? 0}
            subtitle="Active user accounts"
          />
        </PermissionGuard>
        <StatCard
          title="Permissions"
          value={user?.permissions.length ?? 0}
          subtitle="Granted to your role"
        />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Shield className="h-5 w-5" />
              Your Access
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {user?.permissions.map((permission) => (
                <Badge key={permission} variant="secondary">
                  {permission}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        <PermissionGuard permission="audit:view">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <ClipboardList className="h-5 w-5" />
                Recent Activity
              </CardTitle>
            </CardHeader>
            <CardContent>
              {auditQuery.isLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                  <Skeleton className="h-10 w-full" />
                </div>
              ) : (
                <div className="space-y-3">
                  {auditQuery.data?.items.map((log, index) => (
                    <motion.div
                      key={log.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.05 }}
                      className="flex items-center justify-between rounded-lg border border-border p-3"
                    >
                      <div>
                        <p className="text-sm font-medium">{log.action}</p>
                        <p className="text-xs text-muted-foreground">{log.entity_type}</p>
                      </div>
                      <Badge variant="outline">{new Date(log.timestamp).toLocaleDateString()}</Badge>
                    </motion.div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </PermissionGuard>

        <PermissionGuard
          permission="user:view"
          fallback={
            <Card>
              <CardContent className="flex items-center gap-3 p-6 text-muted-foreground">
                <Users className="h-5 w-5" />
                User management requires user:view permission
              </CardContent>
            </Card>
          }
        >
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              Use the sidebar to manage users, roles, permissions, and audit logs based on your
              assigned access level.
            </CardContent>
          </Card>
        </PermissionGuard>
      </div>
    </div>
  );
}
