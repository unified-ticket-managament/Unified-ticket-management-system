"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { ErrorState } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { permissionService, roleService } from "@/services";

export default function PermissionsPage() {
  const queryClient = useQueryClient();
  const [selectedRoleId, setSelectedRoleId] = useState<string>("");
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<string[]>([]);

  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: roleService.list,
  });

  const permissionsQuery = useQuery({
    queryKey: ["permissions"],
    queryFn: permissionService.list,
  });

  const rolePermissionsQuery = useQuery({
    queryKey: ["role-permissions", selectedRoleId],
    queryFn: () => permissionService.getRolePermissions(selectedRoleId),
    enabled: !!selectedRoleId,
  });

  useEffect(() => {
    if (rolePermissionsQuery.data) {
      setSelectedPermissionIds(rolePermissionsQuery.data.map((p) => p.id));
    }
  }, [rolePermissionsQuery.data]);

  useEffect(() => {
    if (rolesQuery.data?.length && !selectedRoleId) {
      setSelectedRoleId(rolesQuery.data[0].id);
    }
  }, [rolesQuery.data, selectedRoleId]);

  const updateMutation = useMutation({
    mutationFn: () =>
      permissionService.updateRolePermissions(selectedRoleId, selectedPermissionIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["role-permissions", selectedRoleId] });
    },
  });

  const togglePermission = (permissionId: string, checked: boolean) => {
    setSelectedPermissionIds((prev) =>
      checked ? [...prev, permissionId] : prev.filter((id) => id !== permissionId)
    );
  };

  return (
    <div>
      <PageHeader
        title="Permission Management"
        description="Assign and revoke permissions for each role"
        action={
          <PermissionGuard permission="permission:update">
            <Button
              onClick={() => updateMutation.mutate()}
              disabled={!selectedRoleId || updateMutation.isPending}
            >
              <Save className="h-4 w-4" />
              Save Changes
            </Button>
          </PermissionGuard>
        }
      />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Select Role</CardTitle>
        </CardHeader>
        <CardContent>
          <Select value={selectedRoleId} onValueChange={setSelectedRoleId}>
            <SelectTrigger className="max-w-md">
              <SelectValue placeholder="Choose a role" />
            </SelectTrigger>
            <SelectContent>
              {rolesQuery.data?.map((role) => (
                <SelectItem key={role.id} value={role.id}>
                  {role.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {(permissionsQuery.isError || rolePermissionsQuery.isError) && (
        <ErrorState message="Failed to load permissions" />
      )}

      {permissionsQuery.isLoading || rolePermissionsQuery.isLoading ? (
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3">
          {permissionsQuery.data?.map((permission) => {
            const checked = selectedPermissionIds.includes(permission.id);
            return (
              <Card key={permission.id}>
                <CardContent className="flex items-center justify-between p-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium">{permission.permission_name}</p>
                      {checked && <Badge variant="success">Assigned</Badge>}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {permission.description || "No description"}
                    </p>
                  </div>
                  <PermissionGuard permission="permission:update">
                    <Checkbox
                      checked={checked}
                      onCheckedChange={(value) =>
                        togglePermission(permission.id, value === true)
                      }
                    />
                  </PermissionGuard>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
