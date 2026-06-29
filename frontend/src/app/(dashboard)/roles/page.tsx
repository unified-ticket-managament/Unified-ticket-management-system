"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { roleService } from "@/services";
import { Role, RoleForm } from "@/types";

const roleSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
});

export default function RolesPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);

  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: roleService.list,
  });

  const form = useForm<RoleForm>({
    resolver: zodResolver(roleSchema),
    defaultValues: { name: "", description: "" },
  });

  const saveMutation = useMutation({
    mutationFn: (data: RoleForm) =>
      editingRole ? roleService.update(editingRole.id, data) : roleService.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      setDialogOpen(false);
      setEditingRole(null);
      form.reset();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: roleService.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["roles"] }),
  });

  const openCreate = () => {
    setEditingRole(null);
    form.reset({ name: "", description: "" });
    setDialogOpen(true);
  };

  const openEdit = (role: Role) => {
    setEditingRole(role);
    form.reset({ name: role.name, description: role.description || "" });
    setDialogOpen(true);
  };

  return (
    <div>
      <PageHeader
        title="Role Management"
        description="Define roles and their access levels"
        action={
          <PermissionGuard permission="role:create">
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4" />
              Create Role
            </Button>
          </PermissionGuard>
        }
      />

      {rolesQuery.isError && <ErrorState message="Failed to load roles" />}

      {rolesQuery.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : rolesQuery.data?.length === 0 ? (
        <EmptyState title="No roles" description="Create your first role to get started." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {rolesQuery.data?.map((role) => (
            <Card key={role.id}>
              <CardHeader>
                <CardTitle>{role.name}</CardTitle>
                <CardDescription>{role.description || "No description"}</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="mb-4 text-xs text-muted-foreground">
                  Created {role.created_at ? formatDate(role.created_at) : "-"}
                </p>
                <div className="flex gap-2">
                  <PermissionGuard permission="role:update">
                    <Button variant="outline" size="sm" onClick={() => openEdit(role)}>
                      <Pencil className="h-4 w-4" />
                      Edit
                    </Button>
                  </PermissionGuard>
                  <PermissionGuard permission="role:delete">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => deleteMutation.mutate(role.id)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                      Delete
                    </Button>
                  </PermissionGuard>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingRole ? "Edit Role" : "Create Role"}</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={form.handleSubmit((data) => saveMutation.mutate(data))}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label>Name</Label>
              <Input {...form.register("name")} />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Input {...form.register("description")} />
            </div>
            <Button type="submit" className="w-full" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Saving..." : "Save Role"}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
