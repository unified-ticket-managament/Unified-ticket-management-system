"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { motion } from "framer-motion";
import {
  Briefcase,
  ClipboardList,
  KeyRound,
  Loader2,
  Shield,
  Ticket,
  Users as UsersIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/shared/stats";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { ROLE_NAMES } from "@/lib/role-access";
import { permissionService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Permission, Role } from "@/types";

const GROUP_LABELS: Record<string, string> = {
  user: "Users",
  role: "Roles",
  permission: "Permissions",
  audit: "Audit Logs",
  dashboard: "Dashboard",
  ticket: "Ticket Management",
};

const GROUP_ICONS: Record<string, typeof Shield> = {
  user: UsersIcon,
  role: Shield,
  permission: KeyRound,
  audit: ClipboardList,
  dashboard: Briefcase,
  ticket: Ticket,
};

function groupLabel(key: string) {
  return GROUP_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

function groupIcon(key: string) {
  return GROUP_ICONS[key] ?? KeyRound;
}

interface RolePermissionsDialogProps {
  role: Role | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RolePermissionsDialog({ role, open, onOpenChange }: RolePermissionsDialogProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);

  // Super Admin can assign any permission. An Account Manager can only
  // assign permissions they personally hold — they can never grant
  // something they don't have themselves. Site Lead — despite holding
  // nearly every backend permission (see canDeleteRecords/canManageRoles
  // in role-access.ts for the broader Site Lead policy) — is
  // deliberately read-only here per product decision: permission
  // editing counts as "modifying role structure", which Site Lead can
  // view but not change. Team Lead / Staff / Viewer cannot manage
  // permissions at all either (read-only).
  const isManagerActor = currentUser?.role === ROLE_NAMES.ACCOUNT_MANAGER;
  const isUnrestrictedActor = currentUser?.role === ROLE_NAMES.SUPER_ADMIN;
  const canManagePermissions = isUnrestrictedActor || isManagerActor;

  const isPermissionAssignable = (permissionName: string) => {
    if (!isManagerActor) return true;
    return currentUser?.permissions.includes(permissionName) ?? false;
  };

  const [selectedPermissionIds, setSelectedPermissionIds] = useState<Set<string>>(new Set());
  const [initialPermissionIds, setInitialPermissionIds] = useState<Set<string>>(new Set());

  const permissionsQuery = useQuery({
    queryKey: ["permissions-all"],
    queryFn: () => permissionService.list({ page: 1, page_size: 100 }),
    enabled: open,
  });

  const rolePermissionsQuery = useQuery({
    queryKey: ["role-permissions", role?.role_id],
    queryFn: () => permissionService.getRolePermissions(role!.role_id),
    enabled: open && !!role?.role_id,
  });

  useEffect(() => {
    if (open && rolePermissionsQuery.data) {
      const ids = new Set<string>(rolePermissionsQuery.data.map((p: Permission) => p.permission_id));
      setSelectedPermissionIds(new Set(ids));
      setInitialPermissionIds(new Set(ids));
    }
  }, [open, rolePermissionsQuery.data]);

  const allPermissions: Permission[] = permissionsQuery.data?.permissions ?? [];

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

      return permissionService.updateRolePermissions(role!.role_id, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-permissions", role?.role_id] });
      toast({
        title: "Permissions updated",
        description: `Changes to the ${role?.name} role have been saved.`,
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

  const isLoading = permissionsQuery.isLoading || rolePermissionsQuery.isLoading;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Permissions for the {role?.name ?? "role"} role</DialogTitle>
        </DialogHeader>

        {canManagePermissions && isManagerActor && (
          <div className="rounded-lg border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
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
                            htmlFor={`role-perm-${permission.permission_id}`}
                            whileTap={!checkboxDisabled ? { scale: 0.98 } : undefined}
                            className={cn(
                              "flex cursor-pointer items-center gap-3 rounded-lg p-2 transition-colors hover:bg-muted/50",
                              checkboxDisabled && "cursor-not-allowed opacity-70"
                            )}
                          >
                            <Checkbox
                              id={`role-perm-${permission.permission_id}`}
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

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
