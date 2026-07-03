"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { motion } from "framer-motion";
import { MoreHorizontal, Pencil, Plus, Shield, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { RoleFormDialog } from "@/components/roles/role-form-dialog";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { roleService, userService } from "@/services";
import { Role, User } from "@/types";

export default function RolesPage() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deletingRole, setDeletingRole] = useState<Role | null>(null);

  const rolesQuery = useQuery({
    queryKey: ["roles-cards"],
    queryFn: () => roleService.list({ page: 1, page_size: 100 }),
  });

  const usersQuery = useQuery({
    queryKey: ["users-for-roles"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const userCounts = useMemo(() => {
    const counts = new Map<string, number>();
    const users: User[] = usersQuery.data?.users ?? [];
    users.forEach((user) => counts.set(user.role_id, (counts.get(user.role_id) ?? 0) + 1));
    return counts;
  }, [usersQuery.data]);

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

  const roles: Role[] = rolesQuery.data?.roles ?? [];

  if (rolesQuery.isError) {
    return <ErrorState message="Failed to load roles. Please try again." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("roles.title")}
        description={`${t("roles.description")}${rolesQuery.data ? ` — ${rolesQuery.data.total} ${t("common.total")}` : ""}.`}
        action={
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
        }
      />

      {rolesQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : roles.length === 0 ? (
        <EmptyState
          title="No roles yet"
          description="Create your first role to start assigning permissions."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {roles.map((role) => {
            const count = userCounts.get(role.role_id) ?? 0;

            return (
              <motion.div key={role.role_id} whileHover={{ y: -4 }} transition={{ type: "spring", stiffness: 300, damping: 22 }}>
                <Card className="h-full transition-shadow hover:shadow-md">
                  <CardContent className="flex items-start justify-between gap-3 p-5">
                    <div className="flex items-start gap-3">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <Shield className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="font-semibold">{role.name}</p>
                        <Badge variant="secondary" className="mt-2 gap-1.5">
                          <Users className="h-3 w-3" />
                          {count} {count === 1 ? "user" : "users"}
                        </Badge>
                      </div>
                    </div>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <PermissionGuard permission="role:update">
                          <DropdownMenuItem
                            onClick={() => {
                              setEditingRole(role);
                            }}
                          >
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
                  </CardContent>
                </Card>
              </motion.div>
            );
          })}
        </div>
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
