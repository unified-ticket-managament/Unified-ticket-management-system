"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { motion } from "framer-motion";
import {
  Briefcase,
  Calendar,
  ClipboardList,
  KeyRound,
  Loader2,
  Mail,
  Shield,
  UserCog,
  Users as UsersIcon,
} from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { EmptyState } from "@/components/shared/stats";
import { useToast } from "@/hooks/use-toast";
import { cn, formatDate } from "@/lib/utils";
import { ROLE_NAMES } from "@/lib/role-access";
import { permissionService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Permission, Role, User } from "@/types";

const GROUP_LABELS: Record<string, string> = {
  user: "Users",
  role: "Roles",
  permission: "Permissions",
  audit: "Audit Logs",
  dashboard: "Dashboard",
};

const GROUP_ICONS: Record<string, typeof Shield> = {
  user: UsersIcon,
  role: Shield,
  permission: KeyRound,
  audit: ClipboardList,
  dashboard: Briefcase,
};

function groupLabel(key: string) {
  return GROUP_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

function groupIcon(key: string) {
  return GROUP_ICONS[key] ?? KeyRound;
}

interface UserDetailDrawerProps {
  user: User | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserDetailDrawer({ user, open, onOpenChange }: UserDetailDrawerProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);

  // Super Admin can assign any permission. A Manager can only assign
  // permissions they personally hold — they can never grant something they
  // don't have themselves. Team Lead / Staff / Viewer cannot manage
  // permissions at all (read-only).
  const isManagerActor = currentUser?.role === ROLE_NAMES.MANAGER;
  const canManagePermissions =
    currentUser?.role === ROLE_NAMES.SUPER_ADMIN || isManagerActor;

  const isPermissionAssignable = (permissionName: string) => {
    if (!isManagerActor) return true;
    return currentUser?.permissions.includes(permissionName) ?? false;
  };

  const [selectedPermissionIds, setSelectedPermissionIds] = useState<Set<string>>(new Set());
  const [initialPermissionIds, setInitialPermissionIds] = useState<Set<string>>(new Set());

  // Shares the "roles-options" and "users-table" query caches with the Users
  // page — no duplicate network requests when opened from there.
  const rolesQuery = useQuery({
    queryKey: ["roles-options"],
    queryFn: () => roleService.list(),
    enabled: open,
  });

  const usersQuery = useQuery({
    queryKey: ["users-table"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
    enabled: open,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions-all"],
    queryFn: () => permissionService.list({ page: 1, page_size: 100 }),
    enabled: open,
  });

  const rolePermissionsQuery = useQuery({
    queryKey: ["role-permissions", user?.role_id],
    queryFn: () => permissionService.getRolePermissions(user!.role_id),
    enabled: open && !!user?.role_id,
  });

  useEffect(() => {
    if (rolePermissionsQuery.data) {
      const ids = new Set<string>(rolePermissionsQuery.data.map((p: Permission) => p.permission_id));
      setSelectedPermissionIds(new Set(ids));
      setInitialPermissionIds(new Set(ids));
    }
  }, [rolePermissionsQuery.data]);

  const roles: Role[] = rolesQuery.data?.roles ?? [];
  const allUsers: User[] = usersQuery.data?.users ?? [];
  const allPermissions: Permission[] = permissionsQuery.data?.permissions ?? [];

  const roleName = useMemo(
    () => roles.find((r) => r.role_id === user?.role_id)?.name ?? "Unassigned",
    [roles, user]
  );
  const managerName = useMemo(
    () => allUsers.find((u) => u.user_id === user?.manager_id)?.name ?? "—",
    [allUsers, user]
  );
  const teamLeadName = useMemo(
    () => allUsers.find((u) => u.user_id === user?.teamlead_id)?.name ?? "—",
    [allUsers, user]
  );

  // Reporting Structure visibility depends on the SELECTED user's role, not
  // the viewer's role: a Manager reports to no one, a Team Lead only
  // reports to a Manager, Staff report to both, and Super Admin has no
  // reporting structure at all.
  const showReportingManager = roleName === ROLE_NAMES.TEAM_LEAD || roleName === ROLE_NAMES.STAFF;
  const showReportingTeamLead = roleName === ROLE_NAMES.STAFF;
  const showReportingStructure = showReportingManager || showReportingTeamLead;

  const groups = useMemo(() => {
    const map = new Map<string, Permission[]>();
    allPermissions.forEach((permission) => {
      const [moduleKey] = permission.permission_name.split(":");
      const key = moduleKey || "other";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(permission);
    });
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [allPermissions]);

  const isDirty = useMemo(() => {
    if (selectedPermissionIds.size !== initialPermissionIds.size) return true;
    for (const id of selectedPermissionIds) {
      if (!initialPermissionIds.has(id)) return true;
    }
    return false;
  }, [selectedPermissionIds, initialPermissionIds]);

  const togglePermission = (permissionId: string, checked: boolean) => {
    setSelectedPermissionIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(permissionId);
      else next.delete(permissionId);
      return next;
    });
  };

  const toggleGroup = (groupPermissions: Permission[], checked: boolean) => {
    setSelectedPermissionIds((prev) => {
      const next = new Set(prev);
      groupPermissions.forEach((permission) => {
        if (isManagerActor && !isPermissionAssignable(permission.permission_name)) return;
        if (checked) next.add(permission.permission_id);
        else next.delete(permission.permission_id);
      });
      return next;
    });
  };

  const updateMutation = useMutation({
    mutationFn: () => {
      // Defensive backstop: a Manager's save can never include a permission
      // they don't personally hold, even if it was somehow present in
      // selectedPermissionIds. The UI already prevents this via disabled
      // checkboxes; this just guarantees it at the request boundary.
      const payload = isManagerActor
        ? Array.from(selectedPermissionIds).filter((id) => {
            const permission = allPermissions.find((p) => p.permission_id === id);
            return !permission || isPermissionAssignable(permission.permission_name);
          })
        : Array.from(selectedPermissionIds);

      return permissionService.updateRolePermissions(user!.role_id, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-permissions", user?.role_id] });
      toast({
        title: "Permissions updated",
        description: `Changes to the ${roleName} role have been saved.`,
      });
      onOpenChange(false);
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to update permissions",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  const handleCancel = () => {
    setSelectedPermissionIds(new Set(initialPermissionIds));
    onOpenChange(false);
  };

  const isLoading =
    rolesQuery.isLoading || usersQuery.isLoading || permissionsQuery.isLoading || rolePermissionsQuery.isLoading;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col p-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>User Details</SheetTitle>
          <SheetDescription>Profile information and role permissions.</SheetDescription>
        </SheetHeader>

        {!user ? null : (
          <div className="flex-1 overflow-y-auto p-4">
            {/* Profile Section */}
            <div className="flex items-center gap-4">
              <Avatar className="h-16 w-16">
                <AvatarFallback className="text-xl">
                  {user.name.charAt(0).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="truncate text-lg font-semibold">{user.name}</p>
                <p className="flex items-center gap-1.5 truncate text-sm text-muted-foreground">
                  <Mail className="h-3.5 w-3.5 shrink-0" />
                  {user.email}
                </p>
              </div>
            </div>

            <dl className="mt-6 grid grid-cols-2 gap-4 rounded-xl border border-border p-4">
              <div>
                <dt className="text-xs text-muted-foreground">Role</dt>
                <dd className="mt-1">
                  <Badge variant="secondary">{roleName}</Badge>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Status</dt>
                <dd className="mt-1">
                  <Badge variant={user.is_active ? "success" : "destructive"}>
                    {user.is_active ? "Active" : "Inactive"}
                  </Badge>
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs text-muted-foreground">Created Date</dt>
                <dd className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                  <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                  {formatDate(user.created_at)}
                </dd>
              </div>
            </dl>

            {/* Reporting Structure — visibility depends on the selected
                user's role. Hidden entirely for Manager and Super Admin. */}
            {showReportingStructure && (
              <div className="mt-4 rounded-xl border border-border p-4">
                <p className="mb-3 text-xs font-medium text-muted-foreground">Reporting Structure</p>
                <dl
                  className={cn(
                    "grid gap-4",
                    showReportingManager && showReportingTeamLead ? "grid-cols-2" : "grid-cols-1"
                  )}
                >
                  {showReportingManager && (
                    <div>
                      <dt className="text-xs text-muted-foreground">Reporting Manager</dt>
                      <dd className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                        <UserCog className="h-3.5 w-3.5 text-muted-foreground" />
                        {managerName}
                      </dd>
                    </div>
                  )}
                  {showReportingTeamLead && (
                    <div>
                      <dt className="text-xs text-muted-foreground">Reporting Team Lead</dt>
                      <dd className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                        <UsersIcon className="h-3.5 w-3.5 text-muted-foreground" />
                        {teamLeadName}
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            )}

            {/* Permission Section */}
            <div className="mt-6">
              <h3 className="mb-3 text-sm font-semibold">Permissions for the {roleName} role</h3>

              {!canManagePermissions && (
                <div className="mb-3 rounded-lg border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
                  You don&apos;t have permission to modify role permissions. Viewing in read-only mode.
                </div>
              )}

              {canManagePermissions && isManagerActor && (
                <div className="mb-3 rounded-lg border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
                  You can only assign permissions that you personally hold. Permissions you don&apos;t
                  have are shown disabled below.
                </div>
              )}

              {isLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-24 w-full rounded-xl" />
                  ))}
                </div>
              ) : groups.length === 0 ? (
                <EmptyState title="No permissions found" description="No permissions are configured yet." />
              ) : (
                <TooltipProvider delayDuration={200}>
                  <div className="space-y-4">
                    {groups.map(([key, groupPermissions]) => {
                      const Icon = groupIcon(key);
                      const selectedCount = groupPermissions.filter((p) =>
                        selectedPermissionIds.has(p.permission_id)
                      ).length;
                      const allSelected = selectedCount === groupPermissions.length;
                      const someSelected = selectedCount > 0 && !allSelected;
                      const groupHasAssignable = groupPermissions.some((p) =>
                        isPermissionAssignable(p.permission_name)
                      );
                      const groupCheckboxDisabled =
                        !canManagePermissions || (isManagerActor && !groupHasAssignable);

                      return (
                        <div key={key} className="rounded-xl border border-border">
                          <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                            <div className="flex items-center gap-2 text-sm font-medium">
                              <Icon className="h-4 w-4 text-primary" />
                              {groupLabel(key)}
                              <Badge variant="secondary" className="ml-1">
                                {selectedCount}/{groupPermissions.length}
                              </Badge>
                            </div>
                            <Checkbox
                              checked={allSelected || (someSelected && "indeterminate")}
                              disabled={groupCheckboxDisabled}
                              onCheckedChange={(checked) => toggleGroup(groupPermissions, !!checked)}
                              aria-label={`Select all ${groupLabel(key)} permissions`}
                            />
                          </div>
                          <div className="space-y-0.5 p-2">
                            {groupPermissions.map((permission) => {
                              const lockedByOwnership =
                                isManagerActor && !isPermissionAssignable(permission.permission_name);
                              const checkboxDisabled = !canManagePermissions || lockedByOwnership;

                              const row = (
                                <motion.label
                                  htmlFor={`drawer-${permission.permission_id}`}
                                  whileTap={!checkboxDisabled ? { scale: 0.98 } : undefined}
                                  className={cn(
                                    "flex cursor-pointer items-center gap-3 rounded-lg p-2 transition-colors hover:bg-muted/50",
                                    checkboxDisabled && "cursor-not-allowed opacity-70"
                                  )}
                                >
                                  <Checkbox
                                    id={`drawer-${permission.permission_id}`}
                                    checked={selectedPermissionIds.has(permission.permission_id)}
                                    disabled={checkboxDisabled}
                                    onCheckedChange={(checked) =>
                                      togglePermission(permission.permission_id, !!checked)
                                    }
                                  />
                                  <span className="font-mono text-sm">{permission.permission_name}</span>
                                </motion.label>
                              );

                              if (!lockedByOwnership) {
                                return <div key={permission.permission_id}>{row}</div>;
                              }

                              return (
                                <Tooltip key={permission.permission_id}>
                                  <TooltipTrigger asChild>
                                    <div>{row}</div>
                                  </TooltipTrigger>
                                  <TooltipContent>Permission not available for your role.</TooltipContent>
                                </Tooltip>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </TooltipProvider>
              )}
            </div>
          </div>
        )}

        <SheetFooter>
          <Button type="button" variant="outline" onClick={handleCancel}>
            Cancel
          </Button>
          {canManagePermissions && (
            <Button
              type="button"
              onClick={() => updateMutation.mutate()}
              disabled={!isDirty || updateMutation.isPending}
            >
              {updateMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save Permissions
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
