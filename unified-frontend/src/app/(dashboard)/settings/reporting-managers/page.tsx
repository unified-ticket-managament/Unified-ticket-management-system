"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Trash2, UserCog } from "lucide-react";

import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { AccessDenied, EmptyState, ErrorState } from "@/components/shared/stats";
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import { categoryService, reportingManagerService, roleService, userService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Category, ReportingManagerAssignment, Role, User } from "@/types";

const ACCOUNT_MANAGER_ROLE_NAME = "Account Manager";

export default function ReportingManagersPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);

  const [selectedAccountManagerId, setSelectedAccountManagerId] = useState<string>("");
  const [selectedCategoryId, setSelectedCategoryId] = useState<string>("");
  const [revoking, setRevoking] = useState<ReportingManagerAssignment | null>(null);

  const canManage = hasPermission("org:manage_reporting_managers");

  const assignmentsQuery = useQuery({
    queryKey: ["reporting-managers"],
    queryFn: () => reportingManagerService.list(),
    enabled: canManage,
  });

  const usersQuery = useQuery({
    queryKey: ["users-for-reporting-managers"],
    queryFn: () => userService.list({ page_size: 100 }),
    enabled: canManage,
  });

  const rolesQuery = useQuery({
    queryKey: ["roles-for-reporting-managers"],
    queryFn: () => roleService.list({ page_size: 100 }),
    enabled: canManage,
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories-for-reporting-managers"],
    queryFn: () => categoryService.list({ page_size: 100 }),
    enabled: canManage,
  });

  const accountManagerRoleId: string | null = useMemo(() => {
    const roles: Role[] = rolesQuery.data?.roles ?? [];
    return roles.find((r) => r.name === ACCOUNT_MANAGER_ROLE_NAME)?.role_id ?? null;
  }, [rolesQuery.data]);

  const accountManagers: User[] = useMemo(() => {
    const users: User[] = usersQuery.data?.users ?? [];
    if (!accountManagerRoleId) return [];
    return users.filter((u) => u.role_id === accountManagerRoleId && u.is_active);
  }, [usersQuery.data, accountManagerRoleId]);

  const categories: Category[] = categoriesQuery.data?.categories ?? [];

  const assignMutation = useMutation({
    mutationFn: () =>
      reportingManagerService.assign({
        account_manager_id: selectedAccountManagerId,
        category_id: selectedCategoryId,
      }),
    onSuccess: () => {
      toast({ title: "Reporting Manager assigned" });
      setSelectedAccountManagerId("");
      setSelectedCategoryId("");
      queryClient.invalidateQueries({ queryKey: ["reporting-managers"] });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        title: "Failed to assign Reporting Manager",
        description: error.response?.data?.detail ?? "Please try again.",
        variant: "destructive",
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (id: string) => reportingManagerService.revoke(id),
    onSuccess: () => {
      toast({ title: "Reporting Manager assignment revoked" });
      setRevoking(null);
      queryClient.invalidateQueries({ queryKey: ["reporting-managers"] });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        title: "Failed to revoke assignment",
        description: error.response?.data?.detail ?? "Please try again.",
        variant: "destructive",
      });
    },
  });

  if (currentUser && !canManage) {
    return (
      <AccessDenied message="You do not have access to manage Reporting Managers." />
    );
  }

  const isLoading =
    assignmentsQuery.isLoading ||
    usersQuery.isLoading ||
    rolesQuery.isLoading ||
    categoriesQuery.isLoading;

  const loadError =
    assignmentsQuery.isError || usersQuery.isError || rolesQuery.isError || categoriesQuery.isError;

  const assignments = assignmentsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Reporting Managers" }]}
      />

      <PageHeader
        title="Reporting Managers"
        description="Assign an Account Manager as the Reporting Manager for one or more business categories — an additional employee-management responsibility, separate from client ownership and from ticket-assignment scope. An Account Manager keeps their own clients regardless of what they're assigned here, and a Reporting Manager assignment never grants access to clients outside their own."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <UserCog className="h-4 w-4" />
            Assign Reporting Manager
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">Account Manager</label>
              <Select value={selectedAccountManagerId} onValueChange={setSelectedAccountManagerId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select an Account Manager" />
                </SelectTrigger>
                <SelectContent>
                  {accountManagers.map((user) => (
                    <SelectItem key={user.user_id} value={user.user_id}>
                      {user.name} — {user.email}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex-1 space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">Category</label>
              <Select value={selectedCategoryId} onValueChange={setSelectedCategoryId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a category" />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((category) => (
                    <SelectItem key={category.category_id} value={category.category_id}>
                      {category.category_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button
              onClick={() => assignMutation.mutate()}
              disabled={
                !selectedAccountManagerId || !selectedCategoryId || assignMutation.isPending
              }
            >
              {assignMutation.isPending ? "Assigning..." : "Assign"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {loadError && <ErrorState message="Failed to load Reporting Manager data." />}

      {!loadError && (
        <Card>
          <CardContent className="p-0">
            {isLoading ? (
              <div className="space-y-3 p-6">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : assignments.length === 0 ? (
              <EmptyState
                title="No Reporting Manager assignments yet"
                description="Assign an Account Manager to a category above to get started."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Account Manager</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Assigned By</TableHead>
                    <TableHead>Assigned At</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {assignments.map((assignment) => (
                    <TableRow key={assignment.id}>
                      <TableCell className="font-medium">
                        {assignment.account_manager_name}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{assignment.category_name}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {assignment.assigned_by_name ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(assignment.assigned_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => setRevoking(assignment)}
                          aria-label="Revoke"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      <AlertDialog open={!!revoking} onOpenChange={(open) => !open && setRevoking(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke Reporting Manager Assignment</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to remove <strong>{revoking?.account_manager_name}</strong> as
              the Reporting Manager for <strong>{revoking?.category_name}</strong>? This only
              affects this HR responsibility — their client ownership and ticket-assignment scope
              are unchanged.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={revokeMutation.isPending}
              onClick={() => revoking && revokeMutation.mutate(revoking.id)}
            >
              Revoke
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
