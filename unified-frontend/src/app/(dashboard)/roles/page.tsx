"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import {
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  KeyRound,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  Shield,
  Trash2,
  Users as UsersIcon,
} from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { MyPermissionsDialog } from "@/components/roles/my-permissions-dialog";
import { RoleFormDialog } from "@/components/roles/role-form-dialog";
import {
  RolePermissionsDialog,
  groupIcon,
  groupLabel,
  groupPermissionsByModule,
} from "@/components/roles/role-permissions-dialog";
import { UserFormDialog } from "@/components/users/user-form-dialog";
import { AccessDenied, EmptyState, ErrorState } from "@/components/shared/stats";
import { WorkflowLoader } from "@/components/common/WorkflowLoader";
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
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { cn, formatDate, getApiErrorMessage } from "@/lib/utils";
import { getCreatableRoleNames, ROLE_NAMES } from "@/lib/role-access";
import { permissionService, roleService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { Permission, Role, User } from "@/types";
import { getClientDetails, listClients } from "@tw/api/clients";
import type { ClientResponse } from "@tw/types";

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
  ROLE_NAMES.CLIENT,
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
  [ROLE_NAMES.CLIENT]: "Client-facing, read-only role scoped to their own account.",
};

const ROLE_LEVELS: Record<string, string> = {
  [ROLE_NAMES.SUPER_ADMIN]: "Level 5 — Super Admin",
  [ROLE_NAMES.SITE_LEAD]: "Level 4 — Site Lead",
  [ROLE_NAMES.ACCOUNT_MANAGER]: "Level 3 — Account Manager",
  [ROLE_NAMES.TEAM_LEAD]: "Level 2 — Team Lead",
  [ROLE_NAMES.STAFF]: "Level 1 — Staff",
  [ROLE_NAMES.CLIENT]: "Unranked — client-facing",
};

function prettifyAction(permissionName: string): string {
  const action = permissionName.split(":")[1] ?? permissionName;
  return action
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Organization email, account manager, and contact emails all come
// from the dedicated GET /clients/{id}/details endpoint (gated by
// client:view) — NOT from the already-fetched, ungated listClients()
// array this page also uses for the collapsed row/count. Fetched
// lazily on first expand, cached per client_id thereafter. Only
// rendered at all when the caller holds client:view — see the
// expanded-panel render site below.
function ClientDetailsPanel({ clientId }: { clientId: string }) {
  const detailsQuery = useQuery({
    queryKey: ["client-details", clientId],
    queryFn: () => getClientDetails(clientId),
  });

  if (detailsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading client details...
      </div>
    );
  }

  if (detailsQuery.isError) {
    return (
      <p className="text-sm text-destructive">
        {getApiErrorMessage(detailsQuery.error, "Failed to load client details.")}
      </p>
    );
  }

  const details = detailsQuery.data;
  if (!details) return null;

  return (
    <>
      <div>
        <p className="text-xs font-medium text-muted-foreground">Organization Email</p>
        <p className="text-sm">{details.inbox_email ?? "—"}</p>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">Account Manager</p>
        <p className="text-sm">
          {details.account_manager_name ?? "Unassigned"}
          {!details.account_manager_active && (
            <span className="ml-2 text-xs text-destructive">
              (no longer an active Account Manager)
            </span>
          )}
        </p>
      </div>
      <div>
        <p className="text-xs font-medium text-muted-foreground">Contact Emails</p>
        {details.contacts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No contact emails on file.</p>
        ) : (
          <ul className="space-y-1">
            {details.contacts.map((contact) => (
              <li key={contact.email} className="text-sm text-muted-foreground">
                • {contact.email}
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

export default function RolesPage() {
  const { toast } = useToast();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  // RBAC Enforcement Audit: previously canManageRoles(currentUser?.role)
  // — a hardcoded Super-Admin-only check that wrapped the Edit/Delete
  // dropdown below and made its own already-correct
  // PermissionGuard("role:update")/("role:delete") unreachable for
  // anyone else, same bug as role:create's button had (see that
  // button's own comment). Site Lead holds both permissions by role
  // default and could already reach both routes via a direct API
  // call, so the hardcoded check was strictly narrower than backend
  // authorization — not a deliberate business rule. This is purely a
  // visibility convenience (avoids showing a "..." trigger that opens
  // to an empty menu for someone holding neither permission);
  // PermissionGuard below remains the actual authorization mechanism
  // for each individual action.
  const canManageRoleActions =
    hasPermission("role:update") || hasPermission("role:delete");
  // Mirrors the backend's PUT /roles/{id}/permissions gate exactly
  // (permission:update — Full for Super Admin/Site Lead, Override-only
  // for everyone else, including Account Manager). Previously
  // hardcoded to Super Admin/Account Manager only, which both missed
  // Site Lead (who holds this permission by default) and over-granted
  // Account Manager (who the RBAC matrix doc keeps override-only).
  const canManagePermissions = hasPermission("permission:update");
  // Gates the entire Client tab's list content (client names/status —
  // not just the expand action's organization email/account
  // manager/contact emails) — a compensating control added alongside
  // widening GET /roles/{id}/users to user:view (see that route's own
  // docstring), which opened this page to Team Lead/Staff for the
  // first time. The expand action's own data (fetched via
  // ClientDetailsPanel below) is separately, additionally gated
  // server-side by the same client:view check on
  // GET /clients/{id}/details — this flag only controls what this
  // page renders from the already-fetched, ungated listClients()
  // array, which stays ungated on purpose (see that fetch's own
  // comment for why: Mail Compose/filter/Rules picker/Create Dummy
  // Mail all depend on it staying unrestricted).
  const canViewClientDetails = hasPermission("client:view");
  // Mirrors the backend's GET /roles/{id}/permissions gate (permission:view)
  // — permissionsQuery previously fetched unconditionally and only branched
  // on isLoading, so a 403 (e.g. Staff, who holds role:view but not
  // permission:view) rendered identically to a genuinely empty role,
  // "No permissions granted". See the roles/[id] detail page's own
  // matching fix for the same bug.
  const canViewPermissions = hasPermission("permission:view");

  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [deletingRole, setDeletingRole] = useState<Role | null>(null);
  const [permissionsDialogOpen, setPermissionsDialogOpen] = useState(false);
  const [myPermissionsOpen, setMyPermissionsOpen] = useState(false);

  // Client-role detail state — Client data/contacts live in
  // `clients`/`client_contacts`, never `users` (see root CLAUDE.md's
  // Client-role section), so this is a parallel query/UI branch
  // rather than a filter over allUsers like every internal role uses.
  const [expandedClientId, setExpandedClientId] = useState<string | null>(null);
  const [clientFormOpen, setClientFormOpen] = useState(false);
  const [editingClient, setEditingClient] = useState<User | null>(null);

  const rolesQuery = useQuery({
    queryKey: ["roles-cards"],
    queryFn: () => roleService.list({ page: 1, page_size: 100 }),
  });

  const clientsQuery = useQuery({
    queryKey: ["clients-list"],
    queryFn: () => listClients(),
  });

  const allRoles: Role[] = rolesQuery.data?.roles ?? [];

  const orderedRoles = useMemo(() => {
    return ROLE_ORDER.map((name) => allRoles.find((r) => r.name === name)).filter(
      (r): r is Role => Boolean(r)
    );
  }, [allRoles]);

  const selectedRole = useMemo(
    () => orderedRoles.find((r) => r.role_id === selectedRoleId) ?? orderedRoles[0] ?? null,
    [orderedRoles, selectedRoleId]
  );

  // Every internal (non-Client) role's FULL, company-wide population —
  // deliberately NOT the hierarchy-scoped GET /users this page used to
  // call (see root CLAUDE.md's Roles-page-visibility note): an Account
  // Manager clicking Team Lead/Staff must see every Team Lead/Staff,
  // not just their own reporting subtree. One query per role via
  // GET /roles/{role_id}/users (gated by role:view + user:view — a
  // real permission check, not a hardcoded role allow-list) — cheap at
  // this table's real size, and each result caches independently by
  // role_id. This intentionally does NOT touch the Users page's own
  // "users-table" query/cache key at all.
  const nonClientRoles = useMemo(
    () => orderedRoles.filter((role) => role.name !== ROLE_NAMES.CLIENT),
    [orderedRoles]
  );

  const roleUsersResults = useQueries({
    queries: nonClientRoles.map((role) => ({
      queryKey: ["role-users", role.role_id],
      queryFn: () => roleService.getUsersForRole(role.role_id),
    })),
  });

  const roleUsersMap = useMemo(() => {
    const map = new Map<string, User[]>();
    nonClientRoles.forEach((role, index) => {
      map.set(role.role_id, roleUsersResults[index]?.data ?? []);
    });
    return map;
  }, [nonClientRoles, roleUsersResults]);

  // Per-role loading flag, purely for the sidebar card counts (see the
  // card render below) — kept separate from the selected-role-scoped
  // loading/error state right after it, which is what the "Assigned
  // Users" panel actually reads.
  const roleUsersLoadingMap = useMemo(() => {
    const map = new Map<string, boolean>();
    nonClientRoles.forEach((role, index) => {
      map.set(role.role_id, roleUsersResults[index]?.isLoading ?? false);
    });
    return map;
  }, [nonClientRoles, roleUsersResults]);

  const userCounts = useMemo(() => {
    const counts = new Map<string, number>();
    roleUsersMap.forEach((users, roleId) => counts.set(roleId, users.length));
    return counts;
  }, [roleUsersMap]);

  const assignedUsers = useMemo(
    () => (selectedRole ? roleUsersMap.get(selectedRole.role_id) ?? [] : []),
    [roleUsersMap, selectedRole]
  );

  // Scoped to whichever role is currently selected — NOT a blanket
  // "did any of the five per-role queries fail" flag. The previous
  // version used `.find(result => result.isError)` across all five
  // results, so a failure fetching (say) Super Admin's population
  // would show an error under the "Assigned Users" panel even while
  // viewing Staff, whose own query had succeeded.
  const selectedRoleIndex = useMemo(
    () => (selectedRole ? nonClientRoles.findIndex((r) => r.role_id === selectedRole.role_id) : -1),
    [nonClientRoles, selectedRole]
  );
  const selectedRoleUsersResult =
    selectedRoleIndex >= 0 ? roleUsersResults[selectedRoleIndex] : undefined;
  const selectedRoleUsersLoading = selectedRoleUsersResult?.isLoading ?? false;
  const selectedRoleUsersError = selectedRoleUsersResult?.isError
    ? selectedRoleUsersResult.error
    : undefined;

  const clients: ClientResponse[] = clientsQuery.data ?? [];
  const isClientRole = selectedRole?.name === ROLE_NAMES.CLIENT;
  const clientRoleId = useMemo(
    () => allRoles.find((r) => r.name === ROLE_NAMES.CLIENT)?.role_id,
    [allRoles]
  );
  const creatableRoleNames = getCreatableRoleNames(currentUser?.role);
  const canCreateClient =
    creatableRoleNames === null || creatableRoleNames.includes(ROLE_NAMES.CLIENT);

  // Reuses UserFormDialog's existing Client-edit branch (see that
  // component's own docstrings) — POST/PUT /users already routes a
  // Client role_id to the `clients` table via UserService, so a
  // `ClientResponse` just needs to be reshaped into the User-shaped
  // object that dialog expects, not a second edit form.
  function clientToEditableUser(client: ClientResponse): User {
    return {
      user_id: client.client_id,
      name: client.name,
      email: client.inbox_email ?? "",
      role_id: clientRoleId ?? "",
      manager_id: client.account_manager_id,
      teamlead_id: null,
      reporting_manager_id: null,
      category_id: null,
      is_active: client.is_active,
      is_on_leave: false,
      created_at: client.created_at,
      updated_at: client.created_at,
      date_of_birth: null,
      alternate_email: null,
      phone_number: null,
      office_location: null,
      department: null,
      team: null,
      designation: null,
      language: null,
      date_format: null,
      time_format: null,
      time_zone: null,
      default_dashboard: null,
    };
  }

  const permissionsQuery = useQuery({
    queryKey: ["role-permissions", selectedRole?.role_id],
    queryFn: () => permissionService.getRolePermissions(selectedRole!.role_id),
    enabled: !!selectedRole && canViewPermissions,
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

  // RBAC Enforcement Audit, Phase 27: role:view is already the backend's
  // sole gate on every route this page calls (roles.py:104,137,181-182) —
  // this page previously had no matching frontend gate at all, so a
  // denied role (Staff) fell through to the generic ErrorState below
  // instead of a proper AccessDenied. Zero access change: every role
  // that could already load this page still can.
  if (currentUser && !hasPermission("role:view")) {
    return <AccessDenied message="You do not have access to the Roles page." />;
  }

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
          // RBAC Enforcement Audit, Phase 48: previously wrapped in
          // `canManage &&` (canManageRoles — hardcoded Super-Admin-only),
          // which incorrectly hid this button from Site Lead (who holds
          // the real role:create permission by default and can already
          // succeed via a direct API call) and from any user individually
          // granted role:create via a personal permission override (the
          // hardcoded check has no way to see an override at all). The
          // PermissionGuard below was already present but inert underneath
          // that stricter wrapper. The separate Edit (role:update)/Delete
          // (role:delete) dropdown below had the identical bug — fixed in
          // a later phase using the same approach.
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
        <WorkflowLoader loading size={56} className="min-h-[500px]" />
      ) : orderedRoles.length === 0 ? (
        <EmptyState
          title="No roles yet"
          description="Create your first role to start assigning permissions."
        />
      ) : (
        <>
        <div className="grid gap-6 lg:grid-cols-[240px_1fr_1fr]">
          {/* Roles List */}
          <div className="space-y-2 lg:h-[560px] lg:overflow-y-auto lg:pr-1">
            {orderedRoles.map((role) => {
              const isSelected = selectedRole?.role_id === role.role_id;
              // Client is sourced from `clients`, never `users` — its
              // card count must reflect that table, not a (always
              // zero) lookup into userCounts.
              const isClient = role.name === ROLE_NAMES.CLIENT;
              const count = isClient ? clients.length : userCounts.get(role.role_id) ?? 0;
              const countLabel = isClient
                ? count === 1
                  ? "client"
                  : "clients"
                : count === 1
                  ? "user"
                  : "users";
              // Only ever true for a non-Client role's own query — the
              // Client tab's count comes from clientsQuery instead,
              // which has its own separate loading state handled
              // elsewhere. Showing a spinner here (rather than "0
              // users") avoids the count flashing 0 -> real number
              // while that role's query is still in flight.
              const isCountLoading = !isClient && (roleUsersLoadingMap.get(role.role_id) ?? false);

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
                        {isClient ? <Building2 className="h-4 w-4" /> : <Shield className="h-4 w-4" />}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{role.name}</p>
                        {isCountLoading ? (
                          <p className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Loader2 className="h-3 w-3 animate-spin" />
                          </p>
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            {count} {countLabel}
                          </p>
                        )}
                      </div>
                    </div>

                    {canManageRoleActions && (
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
              the `lg` breakpoint. On desktop both are fixed-height cards
              matching the Roles List's own height, with their own
              independently-scrolling body (header/button stay fixed) —
              the same bounded-scroll idea Assigned Users/Clients below
              already use, applied to this row instead. */}
          {!selectedRole ? (
            <div className="lg:col-span-2">
              <EmptyState
                title="Select a role"
                description="Choose a role from the list to view its details."
              />
            </div>
          ) : (
            <>
              <Card className="flex flex-col lg:h-[560px]">
                <CardHeader>
                  <CardTitle className="text-base">Role Information</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-4 sm:grid-cols-2 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
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
                  {!isClientRole && (
                    <div>
                      <p className="text-xs text-muted-foreground">Role Level</p>
                      <p className="mt-1 font-medium">{ROLE_LEVELS[selectedRole.name] ?? "—"}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-xs text-muted-foreground">
                      {isClientRole ? "Total Clients" : "Total Assigned Users"}
                    </p>
                    <Badge variant="secondary" className="mt-1 w-fit gap-1.5">
                      {isClientRole ? (
                        <Building2 className="h-3 w-3" />
                      ) : (
                        <UsersIcon className="h-3 w-3" />
                      )}
                      {isClientRole ? (
                        clients.length
                      ) : selectedRoleUsersLoading ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        assignedUsers.length
                      )}
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

              <Card className="flex flex-col lg:h-[560px]">
                <CardHeader className="flex flex-row items-center justify-between space-y-0">
                  <CardTitle className="text-base">Permissions</CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={!canManagePermissions}
                    title={
                      canManagePermissions
                        ? undefined
                        : "You do not have permission to manage permissions."
                    }
                    onClick={() => setPermissionsDialogOpen(true)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    Manage Permissions
                  </Button>
                </CardHeader>
                <CardContent className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
                  {!canViewPermissions ? (
                    <EmptyState
                      title="Access restricted"
                      description="You do not have permission to view this role's permissions."
                    />
                  ) : permissionsQuery.isLoading ? (
                    <WorkflowLoader loading size={40} />
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

        {/* Assigned Users (internal roles) / Clients (Client role) —
            full width below the row above. Bounded height with its
            own scrollbar once the list grows past it, so Role
            Information/Permissions never move or scroll. */}
        {selectedRole && !isClientRole && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Assigned Users</CardTitle>
            </CardHeader>
            <CardContent className="max-h-[420px] space-y-1 overflow-y-auto">
              {selectedRoleUsersLoading ? (
                <WorkflowLoader loading size={40} />
              ) : selectedRoleUsersError ? (
                <ErrorState message={getApiErrorMessage(selectedRoleUsersError, "Failed to load users for this role.")} />
              ) : assignedUsers.length === 0 ? (
                <EmptyState title="No users assigned" description="Users with this role will appear here." />
              ) : (
                assignedUsers.map((user) => {
                  // Comparison is by the stable user_id, never by
                  // name/email — this is the only affordance that opens
                  // the self-service "My Permissions" viewer, and it
                  // must never be reachable for anyone else's row.
                  const isSelf = !!currentUser?.user_id && user.user_id === currentUser.user_id;

                  return (
                    <div
                      key={user.user_id}
                      role={isSelf ? "button" : undefined}
                      tabIndex={isSelf ? 0 : undefined}
                      onClick={isSelf ? () => setMyPermissionsOpen(true) : undefined}
                      onKeyDown={
                        isSelf
                          ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                setMyPermissionsOpen(true);
                              }
                            }
                          : undefined
                      }
                      className={cn(
                        "flex flex-wrap items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-muted/50",
                        isSelf && "cursor-pointer"
                      )}
                    >
                      <Avatar className="h-9 w-9">
                        <AvatarFallback>{user.name.charAt(0).toUpperCase()}</AvatarFallback>
                      </Avatar>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{user.name}</p>
                        <p className="truncate text-xs text-muted-foreground">{user.email}</p>
                      </div>
                      {isSelf && (
                        <Badge variant="secondary" className="shrink-0">
                          You — View Permissions
                        </Badge>
                      )}
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
                  );
                })
              )}
            </CardContent>
          </Card>
        )}

        {selectedRole && isClientRole && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Clients</CardTitle>
              {canCreateClient && (
                <PermissionGuard permission="user:create">
                  <Button
                    size="sm"
                    className="gap-1.5"
                    onClick={() => {
                      setEditingClient(null);
                      setClientFormOpen(true);
                    }}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Create Client
                  </Button>
                </PermissionGuard>
              )}
            </CardHeader>
            <CardContent className="max-h-[420px] space-y-1 overflow-y-auto p-0">
              {clientsQuery.isLoading ? (
                <WorkflowLoader loading size={40} />
              ) : clientsQuery.isError ? (
                <ErrorState
                  message={getApiErrorMessage(clientsQuery.error, "Failed to load clients.")}
                />
              ) : !canViewClientDetails ? (
                // Without client:view, the entire roster is hidden — not
                // just the expand action's org email/account manager/
                // contact emails (see ClientDetailsPanel below). A row
                // never renders at all in this branch, so the two
                // per-row canViewClientDetails checks that used to live
                // inside the .map() below were removed as dead code.
                <div className="p-4">
                  <p className="text-sm text-muted-foreground">
                    You do not have permission to view client details.
                  </p>
                </div>
              ) : clients.length === 0 ? (
                <EmptyState
                  title="No clients yet"
                  description="Create one with the button above."
                />
              ) : (
                <div className="divide-y divide-border">
                  {clients.map((client) => {
                    const isExpanded = expandedClientId === client.client_id;
                    return (
                      <div key={client.client_id}>
                        <button
                          type="button"
                          className="flex w-full items-center justify-between gap-3 p-3 text-left transition-colors hover:bg-muted/50"
                          onClick={() =>
                            setExpandedClientId(isExpanded ? null : client.client_id)
                          }
                        >
                          <div className="flex min-w-0 items-center gap-2">
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                            ) : (
                              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                            )}
                            <Avatar className="h-9 w-9 shrink-0">
                              <AvatarFallback>{client.name.charAt(0).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium">{client.name}</p>
                              <p className="truncate text-xs text-muted-foreground">
                                {client.inbox_email ?? "No organization email"}
                              </p>
                            </div>
                          </div>
                          <div
                            className="flex shrink-0 items-center gap-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Badge variant={client.is_active ? "success" : "destructive"}>
                              {client.is_active ? "Active" : "Inactive"}
                            </Badge>
                            <PermissionGuard permission="user:update">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8"
                                aria-label="Edit client"
                                onClick={() => setEditingClient(clientToEditableUser(client))}
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                            </PermissionGuard>
                          </div>
                        </button>

                        {isExpanded && (
                          <div className="space-y-3 border-t border-border bg-muted/30 p-4 pl-11">
                            <ClientDetailsPanel clientId={client.client_id} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
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

      {/* Reuses UserFormDialog's existing Client-role branch — see
          clientToEditableUser above — rather than a second Client
          creation/edit form. */}
      <UserFormDialog
        open={clientFormOpen || !!editingClient}
        onOpenChange={(open) => {
          if (!open) {
            setClientFormOpen(false);
            setEditingClient(null);
          }
        }}
        user={editingClient}
        defaultRoleId={clientRoleId}
      />

      <RolePermissionsDialog
        role={selectedRole}
        open={permissionsDialogOpen}
        onOpenChange={setPermissionsDialogOpen}
      />

      <MyPermissionsDialog open={myPermissionsOpen} onOpenChange={setMyPermissionsOpen} />

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
