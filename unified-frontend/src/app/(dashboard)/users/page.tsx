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
  Eye,
  KeyRound,
  LogIn,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Tags,
  Trash2,
  UserCog,
} from "lucide-react";
import Link from "next/link";
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
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { DataTable, DataTablePagination } from "@/components/shared/data-table";
import { AccessDenied, ErrorState } from "@/components/shared/stats";
import { CategoryMultiSelect } from "@/components/users/CategoryMultiSelect";
import { UserDetailDrawer } from "@/components/users/user-detail-drawer";
import { UserFormDialog } from "@/components/users/user-form-dialog";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { formatDate, getApiErrorMessage } from "@/lib/utils";
import { canDeleteRecords, canImpersonate, dedupeRolesByName, ROLE_NAMES } from "@/lib/role-access";
import { categoryService, roleService, userService } from "@/services";
import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { useAuthStore } from "@/store/auth-store";
import { useImpersonationStore } from "@/store/impersonation-store";
import { Category, Role, User } from "@/types";

type UserRow = User & { roleName: string; categoryNames: string[] };

// Not a real role_id — a synthetic value for the Role filter's
// "Reporting Manager" option (see the filter's own comment below).
// Never collides with a real role_id UUID.
const REPORTING_MANAGER_FILTER_VALUE = "__reporting_manager__";

const USERS_PAGE_ALLOWED_ROLES: string[] = [
  ROLE_NAMES.SUPER_ADMIN,
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.ACCOUNT_MANAGER,
  ROLE_NAMES.TEAM_LEAD,
  ROLE_NAMES.STAFF,
];

export default function UsersPage() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const canDelete = canDeleteRecords(currentUser?.role);
  // Visible to every role that reaches this page (see
  // USERS_PAGE_ALLOWED_ROLES above); enabled/disabled purely by the
  // caller's effective role:view permission — the same permission the
  // backend already requires on GET /roles and GET /roles/{id}. This
  // used to be a hardcoded three-role allowlist (Super Admin/Site
  // Lead/Account Manager) that hid the button entirely for everyone
  // else; it's now permission-driven so Team Lead/Staff can also reach
  // Roles once granted role:view (via role default or a personal
  // override), with no role-name special-casing.
  const canViewRoles = hasPermission("role:view");

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [categoryFilters, setCategoryFilters] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  const [formOpen, setFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [deletingUser, setDeletingUser] = useState<User | null>(null);
  const [viewingUser, setViewingUser] = useState<User | null>(null);
  const [impersonatingUser, setImpersonatingUser] = useState<UserRow | null>(null);
  const startImpersonation = useImpersonationStore((s) => s.startImpersonation);

  const usersQuery = useQuery({
    // Distinct from the plain ["users-table"] key shared by Audit Logs
    // and the User Detail Drawer — this page's own fetch requests a
    // widened, reporting-scope-aware result those pages don't want,
    // so it must not share their cache entry. Existing
    // invalidateQueries({queryKey: ["users-table"]}) calls elsewhere
    // (e.g. UserFormDialog's onSuccess) still correctly invalidate
    // this nested key too, via TanStack Query's default prefix match.
    queryKey: ["users-table", "reporting-scope"],
    queryFn: () =>
      userService.list({ page: 1, page_size: 100, include_reporting_scope: true }),
  });

  const rolesQuery = useQuery({
    queryKey: ["roles-options"],
    queryFn: () => roleService.list(),
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories-options"],
    queryFn: () => categoryService.list({ page_size: 100 }),
  });

  const isRefreshing = usersQuery.isFetching || rolesQuery.isFetching || categoriesQuery.isFetching;
  function handleRefresh() {
    usersQuery.refetch();
    rolesQuery.refetch();
    categoriesQuery.refetch();
  }

  const dedupedRoles = useMemo(() => dedupeRolesByName<Role>(rolesQuery.data?.roles ?? []), [rolesQuery.data]);

  const roleMap = useMemo(() => {
    const map = new Map<string, string>();
    dedupedRoles.forEach((role: Role) => map.set(role.role_id, role.name));
    return map;
  }, [dedupedRoles]);

  const categoryMap = useMemo(() => {
    const map = new Map<string, string>();
    (categoriesQuery.data?.categories ?? []).forEach((category: Category) =>
      map.set(category.category_id, category.category_name)
    );
    return map;
  }, [categoriesQuery.data]);

  const rows: UserRow[] = useMemo(() => {
    const users: User[] = usersQuery.data?.users ?? [];
    return users.map((user) => {
      const categoryIds = user.category_ids ?? (user.category_id ? [user.category_id] : []);
      return {
        ...user,
        roleName: roleMap.get(user.role_id) ?? "Unassigned",
        categoryNames: categoryIds.map((id) => categoryMap.get(id) ?? "Unknown"),
      };
    });
  }, [usersQuery.data, roleMap, categoryMap]);

  // Server-side scoping (UserService.list_users' include_reporting_scope
  // path) is now authoritative for who appears in `rows` at all — the
  // only client-side narrowing left is Super Admin/Site Lead hiding
  // peer Super Admin rows, a display preference unrelated to
  // visibility scoping. Re-applying the old narrow manager_id/
  // teamlead_id checks here would clip the backend's now-widened
  // (Reporting-Manager-aware) scope right back down.
  const hierarchyRows = useMemo(() => {
    if (!currentUser) return [];
    if (currentUser.role === ROLE_NAMES.SUPER_ADMIN || currentUser.role === ROLE_NAMES.SITE_LEAD) {
      return rows.filter((user) => user.roleName !== ROLE_NAMES.SUPER_ADMIN);
    }
    return rows;
  }, [rows, currentUser]);

  const filteredRows = useMemo(() => {
    return hierarchyRows.filter((user) => {
      if (roleFilter === REPORTING_MANAGER_FILTER_VALUE) {
        if (!user.is_reporting_manager) return false;
      } else if (roleFilter !== "all" && user.role_id !== roleFilter) {
        return false;
      }
      if (categoryFilters.length > 0) {
        const userCategoryIds = user.category_ids ?? (user.category_id ? [user.category_id] : []);
        if (!userCategoryIds.some((id) => categoryFilters.includes(id))) return false;
      }
      if (statusFilter === "active" && !user.is_active) return false;
      if (statusFilter === "inactive" && user.is_active) return false;

      if (search.trim()) {
        const query = search.toLowerCase();
        return (
          user.name.toLowerCase().includes(query) ||
          user.email.toLowerCase().includes(query) ||
          (user.employee_number?.toLowerCase().includes(query) ?? false)
        );
      }

      return true;
    });
  }, [hierarchyRows, search, roleFilter, categoryFilters, statusFilter]);

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

  const impersonateMutation = useMutation({
    mutationFn: (targetUserId: string) => startImpersonation(targetUserId, currentUser),
    onSuccess: () => {
      // startImpersonation itself hard-navigates on success — nothing
      // further to do here, but onSuccess still fires first if the
      // navigation is momentarily deferred by the browser.
      setImpersonatingUser(null);
    },
    onError: (error) => {
      toast({
        variant: "destructive",
        title: "Failed to start impersonation",
        description: getApiErrorMessage(error, "Please try again."),
      });
    },
  });

  const handleExport = () => {
    const selectedIds = Object.keys(rowSelection).filter((id) => rowSelection[id]);
    const source =
      selectedIds.length > 0
        ? filteredRows.filter((_, index) => selectedIds.includes(String(index)))
        : filteredRows;

    const header = ["Name", "Email", "Role", "Category", "Status", "Created At"];
    const csvRows = source.map((user) =>
      [
        user.name,
        user.email,
        user.roleName,
        user.categoryNames.join("; ") || "—",
        user.is_active ? "Active" : "Inactive",
        user.created_at,
      ]
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
          <div onClick={(e) => e.stopPropagation()}>
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(value) => row.toggleSelected(!!value)}
              aria-label="Select row"
            />
          </div>
        ),
        enableSorting: false,
      },
      {
        accessorKey: "employee_number",
        header: "Employee ID",
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.employee_number ?? "—"}</span>
        ),
      },
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => (
          <div className="flex items-center gap-3">
            <Avatar className="h-9 w-9">
              <AvatarFallback>{row.original.name.charAt(0).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="font-medium transition-colors hover:text-primary">
              {row.original.name}
            </span>
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
        accessorKey: "categoryNames",
        header: "Categories",
        cell: ({ row }) =>
          row.original.categoryNames.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {row.original.categoryNames.map((name) => (
                <Badge key={name} variant="secondary">
                  {name}
                </Badge>
              ))}
            </div>
          ) : (
            <Badge variant="outline">—</Badge>
          ),
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
            <div
              className="flex items-center justify-end gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="View user"
                onClick={() => setViewingUser(user)}
              >
                <Eye className="h-4 w-4" />
              </Button>
              <PermissionGuard permission="user:update">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label="Edit user"
                  onClick={() => setEditingUser(user)}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label={user.is_active ? "Deactivate user" : "Activate user"}
                  onClick={() =>
                    statusMutation.mutate({ id: user.user_id, activate: !user.is_active })
                  }
                >
                  {user.is_active ? (
                    <Ban className="h-4 w-4" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" />
                  )}
                </Button>
              </PermissionGuard>
              {canDelete && (
                <PermissionGuard permission="user:delete">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive hover:text-destructive"
                    aria-label="Delete user"
                    onClick={() => setDeletingUser(user)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </PermissionGuard>
              )}
              {canImpersonate(currentUser?.user_id, user.user_id, user.roleName, user.is_active) && (
                <PermissionGuard permission="user:impersonate">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    aria-label="Login as user"
                    onClick={() => setImpersonatingUser(user)}
                  >
                    <LogIn className="h-4 w-4" />
                  </Button>
                </PermissionGuard>
              )}
            </div>
          );
        },
      },
    ],
    [statusMutation, canDelete, currentUser]
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

  if (currentUser && !USERS_PAGE_ALLOWED_ROLES.includes(currentUser.role)) {
    return <AccessDenied message="You do not have access to the Users page." />;
  }

  if (usersQuery.isError) {
    return (
      <ErrorState
        message={getApiErrorMessage(usersQuery.error, "Failed to load users. Please try again.")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Users" }]} />

      <PageHeader
        title={t("users.title")}
        description={`${t("users.description")}${usersQuery.data ? ` — ${hierarchyRows.length} ${t("common.total")}` : ""}.`}
        action={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={handleRefresh}
              disabled={isRefreshing}
              aria-label="Refresh"
              title="Refresh"
            >
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
            </Button>
            <Button variant="outline" className="gap-2" asChild>
              <Link href="/permission-requests">
                <KeyRound className="h-4 w-4" />
                Permission Requests
              </Link>
            </Button>
            <Button variant="outline" className="gap-2" asChild>
              <Link href="/categories">
                <Tags className="h-4 w-4" />
                Categories
              </Link>
            </Button>
            {canViewRoles ? (
              <Button variant="outline" className="gap-2" asChild>
                <Link href="/roles">
                  <Shield className="h-4 w-4" />
                  Roles
                </Link>
              </Button>
            ) : (
              <Button
                variant="outline"
                className="gap-2"
                disabled
                title="You do not have permission to view roles."
              >
                <Shield className="h-4 w-4" />
                Roles
              </Button>
            )}
            <PermissionGuard permission="user:create">
              <Button
                className="gap-2"
                onClick={() => {
                  setEditingUser(null);
                  setFormOpen(true);
                }}
              >
                <Plus className="h-4 w-4" />
                {t("users.createButton")}
              </Button>
            </PermissionGuard>
          </div>
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
              {dedupedRoles
                .filter((role: Role) => role.name !== ROLE_NAMES.CLIENT)
                .map((role: Role) => (
                  <SelectItem key={role.role_id} value={role.role_id}>
                    {role.name}
                  </SelectItem>
                ))}
              {/* Not a real Role — a synthetic option filtering to users
                  who hold a Reporting Manager (reporting_manager_teams)
                  assignment, via the is_reporting_manager flag backend
                  now computes. See REPORTING_MANAGER_FILTER_VALUE above. */}
              <SelectItem value={REPORTING_MANAGER_FILTER_VALUE}>Reporting Manager</SelectItem>
            </SelectContent>
          </Select>

          <CategoryMultiSelect
            categories={categoriesQuery.data?.categories ?? []}
            selectedIds={categoryFilters}
            onChange={setCategoryFilters}
            placeholder="Category"
            className="w-full sm:w-52"
          />

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
        onRowClick={(user) => setViewingUser(user)}
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

      <UserDetailDrawer
        user={viewingUser}
        open={!!viewingUser}
        onOpenChange={(open) => !open && setViewingUser(null)}
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

      <AlertDialog
        open={!!impersonatingUser}
        onOpenChange={(open) => !open && setImpersonatingUser(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <LogIn className="h-5 w-5 text-warning" />
              Login as User
            </AlertDialogTitle>
            <AlertDialogDescription>
              You will act as <strong>{impersonatingUser?.name}</strong> (
              {impersonatingUser?.roleName}) for up to 30 minutes. Every action you
              take will be recorded in the audit trail as performed by them, with
              your own account attributed as the impersonator. You can exit at any
              time from the banner shown while impersonating.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={impersonateMutation.isPending}
              onClick={() =>
                impersonatingUser && impersonateMutation.mutate(impersonatingUser.user_id)
              }
            >
              {impersonateMutation.isPending ? "Starting..." : "Login as User"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
