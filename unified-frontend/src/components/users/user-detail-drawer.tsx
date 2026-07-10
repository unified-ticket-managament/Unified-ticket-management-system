"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Mail, UserCog, Users as UsersIcon } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { UserPermissionOverrides } from "@/components/users/user-permission-overrides";
import { cn, formatDate } from "@/lib/utils";
import { ROLE_NAMES } from "@/lib/role-access";
import { categoryService, permissionService, roleService, userService } from "@/services";
import { Category, Permission, Role, User } from "@/types";

interface UserDetailDrawerProps {
  user: User | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserDetailDrawer({ user, open, onOpenChange }: UserDetailDrawerProps) {
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

  const categoriesQuery = useQuery({
    queryKey: ["categories-options"],
    queryFn: () => categoryService.list({ page_size: 100 }),
    enabled: open,
  });

  // Needed by UserPermissionOverrides below — the full permission catalog
  // and this user's role's own bundle, so it can offer only permissions
  // the role doesn't already grant.
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

  const roles: Role[] = rolesQuery.data?.roles ?? [];
  const allUsers: User[] = usersQuery.data?.users ?? [];
  const allPermissions: Permission[] = permissionsQuery.data?.permissions ?? [];
  const categories: Category[] = categoriesQuery.data?.categories ?? [];

  const roleName = useMemo(
    () => roles.find((r) => r.role_id === user?.role_id)?.name ?? "Unassigned",
    [roles, user]
  );
  const categoryName = useMemo(
    () => categories.find((c) => c.category_id === user?.category_id)?.category_name ?? null,
    [categories, user]
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

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col p-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>User Details</SheetTitle>
          <SheetDescription>
            Profile information and this person&apos;s individual permission grants. To change
            what the {roleName} role itself grants, edit the role from the Roles page instead.
          </SheetDescription>
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
              {categoryName && (
                <div>
                  <dt className="text-xs text-muted-foreground">Category</dt>
                  <dd className="mt-1">
                    <Badge variant="outline">{categoryName}</Badge>
                  </dd>
                </div>
              )}
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
                      <dt className="text-xs text-muted-foreground">Reporting Account Manager</dt>
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

            <UserPermissionOverrides
              user={user}
              roleName={roleName}
              rolePermissions={rolePermissionsQuery.data ?? []}
              allPermissions={allPermissions}
              enabled={open}
            />
          </div>
        )}

        <SheetFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
