"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ColumnDef,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  RowSelectionState,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  Ban,
  CheckCircle2,
  Download,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Trash2,
  UserCog,
} from "lucide-react";
import { useMemo, useState } from "react";

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
import { PageHeader } from "@/components/layout/dashboard-shell";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { ErrorState } from "@/components/shared/stats";
import { UserFormDialog } from "@/components/users/user-form-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import { roleService, userService } from "@/services";
import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { Role, User } from "@/types";

type UserRow = User & { roleName: string };

export default function UsersPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const [formOpen, setFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [deletingUser, setDeletingUser] = useState<User | null>(null);

  const usersQuery = useQuery({
    queryKey: ["users-table"],
    queryFn: () => userService.list({ page: 1, page_size: 100 }),
  });

  const rolesQuery = useQuery({
    queryKey: ["roles-options"],
    queryFn: () => roleService.list(),
  });

  const roleMap = useMemo(() => {
    const map = new Map<string, string>();
    (rolesQuery.data?.roles ?? []).forEach((role: Role) => map.set(role.role_id, role.name));
    return map;
  }, [rolesQuery.data]);

  const rows: UserRow[] = useMemo(() => {
    const users: User[] = usersQuery.data?.users ?? [];
    return users.map((user) => ({ ...user, roleName: roleMap.get(user.role_id) ?? "Unassigned" }));
  }, [usersQuery.data, roleMap]);

  const filteredRows = useMemo(() => {
    return rows.filter((user) => {
      if (roleFilter !== "all" && user.role_id !== roleFilter) return false;
      if (statusFilter === "active" && !user.is_active) return false;
      if (statusFilter === "inactive" && user.is_active) return false;

      if (search.trim()) {
        const query = search.toLowerCase();
        return (
          user.name.toLowerCase().includes(query) || user.email.toLowerCase().includes(query)
        );
      }

      return true;
    });
  }, [rows, search, roleFilter, statusFilter]);

  const deleteMutation = useMutation({
    mutationFn: (id: string) => userService.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users-table"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-users"] });
      toast({ title: "User deleted", description: "The user has been removed." });
      setDeletingUser(null);
    },
    onError: () => {
      toast({ variant: "destructive", title: "Failed to delete user" });
    },
  });

  const statusMutation = useMutation({
    mutationFn: ({ id, activate }: { id: string; activate: boolean }) =>
      activate ? userService.activate(id) : userService.deactivate(id),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["users-table"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-users"] });
      toast({
        title: variables.activate ? "User activated" : "User deactivated",
      });
    },
    onError: () => {
      toast({ variant: "destructive", title: "Failed to update user status" });
    },
  });

  const handleExport = () => {
    const selectedIds = Object.keys(rowSelection).filter((id) => rowSelection[id]);
    const source =
      selectedIds.length > 0
        ? filteredRows.filter((_, index) => selectedIds.includes(String(index)))
        : filteredRows;

    const header = ["Name", "Email", "Role", "Status", "Created At"];
    const csvRows = source.map((user) =>
      [user.name, user.email, user.roleName, user.is_active ? "Active" : "Inactive", user.created_at]
        .map((value) => `"${String(value).replace(/"/g, '""')}"`)
        .join(",")
    );
    const csv = [header.join(","), ...csvRows].join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `users-export-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);

    toast({ title: "Export ready", description: `${source.length} user(s) exported.` });
  };

  const columns = useMemo<ColumnDef<UserRow>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && "indeterminate")
            }
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
            aria-label="Select all"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label="Select row"
          />
        ),
        enableSorting: false,
      },
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => (
          <div className="flex items-center gap-3">
            <Avatar className="h-9 w-9">
              <AvatarFallback>{row.original.name.charAt(0).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="font-medium">{row.original.name}</span>
          </div>
        ),
      },
      {
        accessorKey: "email",
        header: "Email",
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "roleName",
        header: "Role",
        cell: ({ row }) => <Badge variant="secondary">{row.original.roleName}</Badge>,
      },
      {
        accessorKey: "is_active",
        header: "Status",
        cell: ({ row }) => (
          <Badge variant={row.original.is_active ? "success" : "destructive"}>
            {row.original.is_active ? "Active" : "Inactive"}
          </Badge>
        ),
      },
      {
        accessorKey: "created_at",
        header: "Created Date",
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatDate(row.original.created_at)}</span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        cell: ({ row }) => {
          const user = row.original;
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <PermissionGuard permission="user:update">
                  <DropdownMenuItem onClick={() => setEditingUser(user)}>
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() =>
                      statusMutation.mutate({ id: user.user_id, activate: !user.is_active })
                    }
                  >
                    {user.is_active ? (
                      <>
                        <Ban className="mr-2 h-4 w-4" />
                        Deactivate
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                        Activate
                      </>
                    )}
                  </DropdownMenuItem>
                </PermissionGuard>
                <PermissionGuard permission="user:delete">
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onClick={() => setDeletingUser(user)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                </PermissionGuard>
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [statusMutation]
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  if (usersQuery.isError) {
    return <ErrorState message="Failed to load users. Please try again." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Users"
        description={`Manage your organization's users${usersQuery.data ? ` — ${usersQuery.data.total} total` : ""}.`}
        action={
          <PermissionGuard permission="user:create">
            <Button
              className="gap-2"
              onClick={() => {
                setEditingUser(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              Create User
            </Button>
          </PermissionGuard>
        }
      />

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search by name or email..."
              className="pl-9"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <Select value={roleFilter} onValueChange={setRoleFilter}>
            <SelectTrigger className="w-full sm:w-44">
              <SelectValue placeholder="Role" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Roles</SelectItem>
              {(rolesQuery.data?.roles ?? []).map((role: Role) => (
                <SelectItem key={role.role_id} value={role.role_id}>
                  {role.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-full sm:w-40">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="inactive">Inactive</SelectItem>
            </SelectContent>
          </Select>

          <Button variant="outline" className="gap-2" onClick={handleExport}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        </CardContent>
      </Card>

      <DataTable
        table={table}
        columnCount={columns.length}
        isLoading={usersQuery.isLoading}
        emptyTitle="No users found"
        emptyDescription="Try adjusting your search or filters, or create a new user."
      />

      <DataTablePagination table={table} showSelectionCount />

      <UserFormDialog
        open={formOpen || !!editingUser}
        onOpenChange={(open) => {
          if (!open) {
            setFormOpen(false);
            setEditingUser(null);
          }
        }}
        user={editingUser}
      />

      <AlertDialog open={!!deletingUser} onOpenChange={(open) => !open && setDeletingUser(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <UserCog className="h-5 w-5 text-destructive" />
              Delete User
            </AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{deletingUser?.name}</strong>? This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => deletingUser && deleteMutation.mutate(deletingUser.user_id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
