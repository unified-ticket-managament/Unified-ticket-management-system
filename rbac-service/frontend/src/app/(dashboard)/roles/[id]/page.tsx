"use client";

import { useQuery } from "@tanstack/react-query";
import { KeyRound, Shield, Users } from "lucide-react";
import { useParams, useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { permissionService, roleService, userService } from "@/services";
import { Permission, Role, User } from "@/types";

export default function RoleDetailsPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const roleQuery = useQuery({
    queryKey: ["role-detail", params.id],
    queryFn: () => roleService.get(params.id),
  });

  const usersQuery = useQuery({
    queryKey: ["users-for-role-detail"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const permissionsQuery = useQuery({
    queryKey: ["role-permissions", params.id],
    queryFn: () => permissionService.getRolePermissions(params.id),
  });

  const role: Role | undefined = roleQuery.data;
  const assignedUsers: User[] = (usersQuery.data?.users ?? []).filter((u: User) => u.role_id === params.id);
  const permissions: Permission[] = permissionsQuery.data ?? [];

  if (roleQuery.isError) {
    return <ErrorState message="Failed to load this role. It may have been deleted." />;
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Roles", href: "/roles" },
          { label: role?.name ?? "Role" },
        ]}
      />

      {roleQuery.isLoading ? (
        <Skeleton className="h-10 w-64" />
      ) : (
        <PageHeader
          title={role?.name ?? "Role"}
          description="Role information and assigned users."
          action={
            <Button variant="outline" onClick={() => router.push("/roles")}>
              Back to Roles
            </Button>
          }
        />
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Role Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Shield className="h-5 w-5" />
                </div>
                <div>
                  <p className="font-semibold">{role?.name ?? "—"}</p>
                  <p className="font-mono text-xs text-muted-foreground">{role?.role_id.slice(0, 8)}</p>
                </div>
              </div>
              <div className="flex items-center justify-between border-t border-border pt-3 text-sm">
                <span className="text-muted-foreground">Assigned Users</span>
                <Badge variant="secondary" className="gap-1.5">
                  <Users className="h-3 w-3" />
                  {assignedUsers.length}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Permissions Granted</span>
                <Badge variant="secondary" className="gap-1.5">
                  <KeyRound className="h-3 w-3" />
                  {permissions.length}
                </Badge>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Permissions</CardTitle>
            </CardHeader>
            <CardContent>
              {permissionsQuery.isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-6 w-full" />
                  ))}
                </div>
              ) : permissions.length === 0 ? (
                <EmptyState title="No permissions granted" description="This role has no permissions assigned yet." />
              ) : (
                <div className="flex flex-wrap gap-2">
                  {permissions.map((p) => (
                    <Badge key={p.permission_id} variant="outline">
                      {p.permission_name}
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Assigned Users</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {usersQuery.isLoading ? (
                Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)
              ) : assignedUsers.length === 0 ? (
                <EmptyState title="No users assigned" description="Users with this role will appear here." />
              ) : (
                assignedUsers.map((user) => (
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
                    <Badge variant={user.is_active ? "success" : "destructive"} className="shrink-0">
                      {user.is_active ? "Active" : "Inactive"}
                    </Badge>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatDate(user.created_at)}</span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
