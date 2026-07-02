"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import {
  ClipboardList,
  KeyRound,
  Loader2,
  Save,
  Search,
  Shield,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { permissionService, roleService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Permission, Role } from "@/types";

const GROUP_LABELS: Record<string, string> = {
  user: "Users",
  role: "Roles",
  permission: "Permissions",
  audit: "Audit Logs",
};

const GROUP_ICONS: Record<string, typeof Shield> = {
  user: Users,
  role: Shield,
  permission: KeyRound,
  audit: ClipboardList,
};

function groupLabel(key: string) {
  return GROUP_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

function groupIcon(key: string) {
  return GROUP_ICONS[key] ?? KeyRound;
}

export default function PermissionsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const canEdit = useAuthStore((s) => s.hasPermission("permission:update"));

  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [search, setSearch] = useState("");
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<Set<string>>(new Set());
  const [initialPermissionIds, setInitialPermissionIds] = useState<Set<string>>(new Set());

  const rolesQuery = useQuery({
    queryKey: ["roles-options"],
    queryFn: () => roleService.list({ page: 1, page_size: 100 }),
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions-all"],
    queryFn: () => permissionService.list({ page: 1, page_size: 100 }),
  });

  const roles: Role[] = rolesQuery.data?.roles ?? [];
  const allPermissions: Permission[] = permissionsQuery.data?.permissions ?? [];

  useEffect(() => {
    if (!selectedRoleId && roles.length > 0) {
      setSelectedRoleId(roles[0].role_id);
    }
  }, [roles, selectedRoleId]);

  const rolePermissionsQuery = useQuery({
    queryKey: ["role-permissions", selectedRoleId],
    queryFn: () => permissionService.getRolePermissions(selectedRoleId),
    enabled: !!selectedRoleId,
  });

  useEffect(() => {
    if (rolePermissionsQuery.data) {
      const ids = new Set<string>(
        rolePermissionsQuery.data.map((p: Permission) => p.permission_id)
      );
      setSelectedPermissionIds(new Set(ids));
      setInitialPermissionIds(new Set(ids));
    }
  }, [rolePermissionsQuery.data]);

  const groups = useMemo(() => {
    const query = search.trim().toLowerCase();

    const filtered = allPermissions.filter((permission) => {
      if (!query) return true;
      return (
        permission.permission_name.toLowerCase().includes(query) ||
        (permission.description ?? "").toLowerCase().includes(query)
      );
    });

    const map = new Map<string, Permission[]>();
    filtered.forEach((permission) => {
      const [moduleKey] = permission.permission_name.split(":");
      const key = moduleKey || "other";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(permission);
    });

    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [allPermissions, search]);

  const isDirty = useMemo(() => {
    if (selectedPermissionIds.size !== initialPermissionIds.size) return true;
    for (const id of selectedPermissionIds) {
      if (!initialPermissionIds.has(id)) return true;
    }
    return false;
  }, [selectedPermissionIds, initialPermissionIds]);

  const updateMutation = useMutation({
    mutationFn: () =>
      permissionService.updateRolePermissions(
        selectedRoleId,
        Array.from(selectedPermissionIds)
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-permissions", selectedRoleId] });
      toast({
        title: "Permissions updated",
        description: `Changes to the ${roles.find((r) => r.role_id === selectedRoleId)?.name ?? "role"} role have been saved.`,
      });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to update permissions",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

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
        if (checked) next.add(permission.permission_id);
        else next.delete(permission.permission_id);
      });
      return next;
    });
  };

  const handleReset = () => {
    setSelectedPermissionIds(new Set(initialPermissionIds));
  };

  if (rolesQuery.isError || permissionsQuery.isError) {
    return <ErrorState message="Failed to load permissions. Please try again." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Permissions"
        description="Assign granular permissions to each role."
      />

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <div className="w-full sm:w-64">
            <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
              <SelectTrigger>
                <SelectValue placeholder={rolesQuery.isLoading ? "Loading roles..." : "Select a role"} />
              </SelectTrigger>
              <SelectContent>
                {roles.map((role) => (
                  <SelectItem key={role.role_id} value={role.role_id}>
                    {role.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search permissions..."
              className="pl-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {!canEdit && (
        <div className="rounded-xl border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
          You don&apos;t have permission to modify role permissions. Viewing in read-only mode.
        </div>
      )}

      {!selectedRoleId ? (
        <EmptyState title="No role selected" description="Select a role above to manage its permissions." />
      ) : rolePermissionsQuery.isLoading || permissionsQuery.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full rounded-xl" />
          ))}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState title="No permissions found" description="Try a different search term." />
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {groups.map(([key, groupPermissions]) => {
              const Icon = groupIcon(key);
              const selectedCount = groupPermissions.filter((p) =>
                selectedPermissionIds.has(p.permission_id)
              ).length;
              const allSelected = selectedCount === groupPermissions.length;
              const someSelected = selectedCount > 0 && !allSelected;

              return (
                <Card key={key}>
                  <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Icon className="h-4 w-4 text-primary" />
                      {groupLabel(key)}
                      <Badge variant="secondary" className="ml-1">
                        {selectedCount}/{groupPermissions.length}
                      </Badge>
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <label
                        htmlFor={`group-${key}`}
                        className="text-xs text-muted-foreground"
                      >
                        Select all
                      </label>
                      <Checkbox
                        id={`group-${key}`}
                        checked={allSelected || (someSelected && "indeterminate")}
                        disabled={!canEdit}
                        onCheckedChange={(checked) => toggleGroup(groupPermissions, !!checked)}
                      />
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-1">
                    {groupPermissions.map((permission) => (
                      <label
                        key={permission.permission_id}
                        htmlFor={permission.permission_id}
                        className={cn(
                          "flex cursor-pointer items-start gap-3 rounded-lg p-2 transition-colors hover:bg-muted/50",
                          !canEdit && "cursor-not-allowed opacity-70"
                        )}
                      >
                        <Checkbox
                          id={permission.permission_id}
                          className="mt-0.5"
                          checked={selectedPermissionIds.has(permission.permission_id)}
                          disabled={!canEdit}
                          onCheckedChange={(checked) =>
                            togglePermission(permission.permission_id, !!checked)
                          }
                        />
                        <div className="min-w-0">
                          <p className="text-sm font-medium">
                            {permission.description || permission.permission_name}
                          </p>
                          <p className="font-mono text-xs text-muted-foreground">
                            {permission.permission_name}
                          </p>
                        </div>
                      </label>
                    ))}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {canEdit && (
            <div className="flex items-center justify-end gap-3 rounded-xl border border-border bg-card p-4 shadow-sm">
              {isDirty && (
                <p className="mr-auto text-sm text-muted-foreground">You have unsaved changes.</p>
              )}
              <Button variant="outline" onClick={handleReset} disabled={!isDirty || updateMutation.isPending}>
                Reset
              </Button>
              <Button
                className="gap-2"
                onClick={() => updateMutation.mutate()}
                disabled={!isDirty || updateMutation.isPending}
              >
                {updateMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Save Changes
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
