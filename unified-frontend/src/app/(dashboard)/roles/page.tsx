"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Check, KeyRound, MoreHorizontal, Pencil, Plus, Shield, Trash2, Users as UsersIcon } from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { RoleFormDialog } from "@/components/roles/role-form-dialog";
import {
  RolePermissionsDialog,
  groupIcon,
  groupLabel,
  groupPermissionsByModule,
} from "@/components/roles/role-permissions-dialog";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { cn, formatDate } from "@/lib/utils";
import { canManageRoles, ROLE_NAMES } from "@/lib/role-access";
import { permissionService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Permission, Role, User } from "@/types";

// Master list is deliberately narrower than the full role catalog — only
// these six, in this exact order. A custom role created via "Create Role"
// still exists and is fully manageable through the API, it just won't
// appear in this list (per the approved design spec for this page).
const ROLE_ORDER: string[] = [
  ROLE_NAMES.STAFF,
  ROLE_NAMES.TEAM_LEAD,
  ROLE_NAMES.ACCOUNT_MANAGER,
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.SUPER_ADMIN,
  ROLE_NAMES.VIEWER,
];

// Presentational-only metadata — the Role model has no description/level
// columns, so this is a frontend lookup, not data from the API. Wording
// mirrors this project's own CLAUDE.md description of each role.
const ROLE_DESCRIPTIONS: Record<string, string> = {
  [ROLE_NAMES.STAFF]: "Front-line agent handling day-to-day tickets and client communication.",
  [ROLE_NAMES.TEAM_LEAD]: "Oversees a team of Staff members and their assigned tickets.",
  [ROLE_NAMES.ACCOUNT_MANAGER]: "Manages a portfolio of client accounts and their Team Leads and Staff.",
  [ROLE_NAMES.SITE_LEAD]: "Full operational oversight across the organization, second only to Super Admin.",
  [ROLE_NAMES.SUPER_ADMIN]: "Unrestricted access to every module, user, and configuration in the system.",
  [ROLE_NAMES.VIEWER]: "Client-facing, read-only role scoped to their own account.",
};

const ROLE_LEVELS: Record<string, string> = {
  [ROLE_NAMES.SUPER_ADMIN]: "Level 5 — Super Admin",
  [ROLE_NAMES.SITE_LEAD]: "Level 4 — Site Lead",
  [ROLE_NAMES.ACCOUNT_MANAGER]: "Level 3 — Account Manager",
  [ROLE_NAMES.TEAM_LEAD]: "Level 2 — Team Lead",
  [ROLE_NAMES.STAFF]: "Level 1 — Staff",
  [ROLE_NAMES.VIEWER]: "Unranked — client-facing",
};

function prettifyAction(permissionName: string): string {
  const action = permissionName.split(":")[1] ?? permissionName;
  return action
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function RolesPage() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const canManage = canManageRoles(currentUser?.role);
  // Mirrors the backend's PUT /roles/{id}/permissions gate exactly
  // (permission:update — Full for Super Admin/Site Lead, Override-only
  // for everyone else, including Account Manager). Previously
  // hardcoded to Super Admin/Account Manager only, which both missed
  // Site Lead (who holds this permission by default) and over-granted
  // Account Manager (who the RBAC matrix doc keeps override-only).
  const canManagePermissions = hasPermission("permission:update");

  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deletingRole, setDeletingRole] = useState<Role | null>(null);
  const [permissionsDialogOpen, setPermissionsDialogOpen] = useState(false);

  const rolesQuery = useQuery({
    queryKey: ["roles-cards"],
    queryFn: () => roleService.list({ page: 1, page_size: 100 }),
  });

  // Same key as the Users page's own "users-table" query (and Audit
  // Logs' matching query) — identical call/params, so TanStack
  // Query's cache (staleTime: 30_000, see query-provider.tsx) shares
  // one request across all three pages instead of a fresh identical
  // fetch every time any of them mounts. Also means a user mutated
  // from the Users page (which invalidates "users-table") correctly
  // invalidates this page's copy too, instead of it silently staying
  // stale until its own 30s window happened to expire.
  const usersQuery = useQuery({
    queryKey: ["users-table"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const allRoles: Role[] = rolesQuery.data?.roles ?? [];
  const allUsers: User[] = usersQuery.data?.users ?? [];

  const orderedRoles = useMemo(() => {
    return ROLE_ORDER.map((name) => allRoles.find((r) => r.name === name)).filter(
      (r): r is Role => Boolean(r)
    );
  }, [allRoles]);

  const selectedRole = useMemo(
    () => orderedRoles.find((r) => r.role_id === selectedRoleId) ?? orderedRoles[0] ?? null,
    [orderedRoles, selectedRoleId]
  );

  const userCounts = useMemo(() => {
    const counts = new Map<string, number>();
    allUsers.forEach((user) => counts.set(user.role_id, (counts.get(user.role_id) ?? 0) + 1));
    return counts;
  }, [allUsers]);

  const assignedUsers = useMemo(
    () => (selectedRole ? allUsers.filter((user) => user.role_id === selectedRole.role_id) : []),
    [allUsers, selectedRole]
  );

  const permissionsQuery = useQuery({
    queryKey: ["role-permissions", selectedRole?.role_id],
    queryFn: () => permissionService.getRolePermissions(selectedRole!.role_id),
    enabled: !!selectedRole,
  });
  const rolePermissions: Permission[] = permissionsQuery.data ?? [];
  const permissionGroups = useMemo(
    () => groupPermissionsByModule(rolePermissions),
    [rolePermissions]
  );

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => roleService.delete(roleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles-cards"] });
      queryClient.invalidateQueries({ queryKey: ["roles-options"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-roles"] });
      toast({ title: "Role deleted", description: "The role has been removed." });
      setDeletingRole(null);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to delete role",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  if (rolesQuery.isError) {
    return <ErrorState message="Failed to load roles. Please try again." />;
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Users", href: "/users" },
          { label: "Roles", href: "/roles" },
          ...(selectedRole ? [{ label: selectedRole.name }] : []),
        ]}
      />

      <PageHeader
        title={t("roles.title")}
        description={`${t("roles.description")}${rolesQuery.data ? ` — ${rolesQuery.data.total} ${t("common.total")}` : ""}.`}
        action={
          canManage && (
            <PermissionGuard permission="role:create">
              <Button
                className="gap-2"
                onClick={() => {
                  setEditingRole(null);
                  setFormOpen(true);
                }}
              >
                <Plus className="h-4 w-4" />
                Create Role
              </Button>
            </PermissionGuard>
          )
        }
      />

      {rolesQuery.isLoading ? (
        <div className="grid gap-6 lg:grid-cols-[240px_1fr_1fr]">
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-96 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      ) : orderedRoles.length === 0 ? (
        <EmptyState
          title="No roles yet"
          description="Create your first role to start assigning permissions."
        />
      ) : (
        <>
        <div className="grid gap-6 lg:grid-cols-[240px_1fr_1fr] lg:items-start">
          {/* Roles List */}
          <div className="space-y-2">
            {orderedRoles.map((role) => {
              const isSelected = selectedRole?.role_id === role.role_id;
              const count = userCounts.get(role.role_id) ?? 0;

              return (
                <Card
                  key={role.role_id}
                  onClick={() => setSelectedRoleId(role.role_id)}
                  className={cn(
                    "cursor-pointer transition-colors",
                    isSelected ? "border-primary bg-primary/5" : "hover:bg-muted/50"
                  )}
                >
                  <CardContent className="flex items-center justify-between gap-2 p-3.5">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <div
                        className={cn(
                          "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
                          isSelected ? "bg-primary text-primary-foreground" : "bg-primary/10 text-primary"
                        )}
                      >
                        <Shield className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{role.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {count} {count === 1 ? "user" : "users"}
                        </p>
                      </div>
                    </div>

                    {canManage && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 shrink-0"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MoreHorizontal className="h-3.5 w-3.5" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <PermissionGuard permission="role:update">
                            <DropdownMenuItem onClick={() => setEditingRole(role)}>
                              <Pencil className="mr-2 h-4 w-4" />
                              Edit
                            </DropdownMenuItem>
                          </PermissionGuard>
                          <PermissionGuard permission="role:delete">
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
                              onClick={() => setDeletingRole(role)}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Delete
                            </DropdownMenuItem>
                          </PermissionGuard>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Role Information | Permissions — side by side with the Roles
              List on desktop; each stacks in normal document order below
              the `lg` breakpoint. Both are plain-height cards (no scroll
              of their own) — only Assigned Users below gets a bounded,
              independently-scrolling area. */}
          {!selectedRole ? (
            <div className="lg:col-span-2">
              <EmptyState
                title="Select a role"
                description="Choose a role from the list to view its details."
              />
            </div>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Role Information</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <p className="text-xs text-muted-foreground">Role Name</p>
                    <p className="mt-1 font-semibold">{selectedRole.name}</p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-xs text-muted-foreground">Description</p>
                    <p className="mt-1 text-sm text-foreground/90">
                      {ROLE_DESCRIPTIONS[selectedRole.name] ?? "No description available."}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Role Level</p>
                    <p className="mt-1 font-medium">{ROLE_LEVELS[selectedRole.name] ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Total Assigned Users</p>
                    <Badge variant="secondary" className="mt-1 w-fit gap-1.5">
                      <UsersIcon className="h-3 w-3" />
                      {assignedUsers.length}
                    </Badge>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Permissions Count</p>
                    <Badge variant="secondary" className="mt-1 w-fit gap-1.5">
                      <KeyRound className="h-3 w-3" />
                      {rolePermissions.length}
                    </Badge>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <CardTitle className="text-base">Permissions</CardTitle>
                  {canManagePermissions && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-1.5"
                      onClick={() => setPermissionsDialogOpen(true)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      Manage Permissions
                    </Button>
                  )}
                </CardHeader>
                <CardContent>
                  {permissionsQuery.isLoading ? (
                    <div className="space-y-2">
                      {Array.from({ length: 3 }).map((_, i) => (
                        <Skeleton key={i} className="h-6 w-full" />
                      ))}
                    </div>
                  ) : permissionGroups.length === 0 ? (
                    <EmptyState
                      title="No permissions granted"
                      description="This role has no permissions assigned yet."
                    />
                  ) : (
                    <div className="space-y-4">
                      {permissionGroups.map(([key, groupPermissions]) => {
                        const Icon = groupIcon(key);
                        return (
                          <div key={key}>
                            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                              <Icon className="h-4 w-4 text-primary" />
                              {groupLabel(key)}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {groupPermissions.map((permission) => (
                                <Badge
                                  key={permission.permission_id}
                                  variant="outline"
                                  className="gap-1.5 font-normal"
                                >
                                  <Check className="h-3 w-3 shrink-0 text-emerald-600" />
                                  {prettifyAction(permission.permission_name)}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {/* Assigned Users — full width below the row above. Bounded
            height with its own scrollbar once the list grows past it,
            so Role Information/Permissions never move or scroll. */}
        {selectedRole && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Assigned Users</CardTitle>
            </CardHeader>
            <CardContent className="max-h-[420px] space-y-1 overflow-y-auto">
              {usersQuery.isLoading ? (
                Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)
              ) : assignedUsers.length === 0 ? (
                <EmptyState title="No users assigned" description="Users with this role will appear here." />
              ) : (
                assignedUsers.map((user) => (
                  <div
                    key={user.user_id}
                    className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50"
                  >
                    <Avatar className="h-9 w-9">
                      <AvatarFallback>{user.name.charAt(0).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{user.name}</p>
                      <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                    </div>
                    <Badge variant="outline" className="shrink-0">
                      {selectedRole.name}
                    </Badge>
                    <Badge variant={user.is_active ? "success" : "destructive"} className="shrink-0">
                      {user.is_active ? "Active" : "Inactive"}
                    </Badge>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatDate(user.created_at)}
                    </span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        )}
        </>
      )}

      <RoleFormDialog
        open={formOpen || !!editingRole}
        onOpenChange={(open) => {
          if (!open) {
            setFormOpen(false);
            setEditingRole(null);
          }
        }}
        role={editingRole}
      />

      <RolePermissionsDialog
        role={selectedRole}
        open={permissionsDialogOpen}
        onOpenChange={setPermissionsDialogOpen}
      />

      <AlertDialog open={!!deletingRole} onOpenChange={(open) => !open && setDeletingRole(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Role</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{deletingRole?.name}</strong>? This action
              cannot be undone. Roles that are still assigned to users cannot be deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => deletingRole && deleteMutation.mutate(deletingRole.role_id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
