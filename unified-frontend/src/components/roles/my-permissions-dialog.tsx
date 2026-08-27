"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Maximize2, Minimize2, Minus } from "lucide-react";

import { ErrorState } from "@/components/shared/stats";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, getApiErrorMessage } from "@/lib/utils";
import { authService } from "@/services";

import { groupIcon, groupLabel, groupPermissionsByModule } from "./role-permissions-dialog";

interface MyPermissionsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Read-only self-service viewer for the authenticated user's own
// effective permissions — no user id is ever passed in, the data comes
// entirely from GET /auth/me/permissions, which is derived server-side
// from the caller's own session. There is no edit affordance here at
// all; managing permissions still only happens through the existing
// RolePermissionsDialog / user-permission-overrides surfaces.
export function MyPermissionsDialog({ open, onOpenChange }: MyPermissionsDialogProps) {
  const [isMaximized, setIsMaximized] = useState(false);

  const query = useQuery({
    queryKey: ["my-permissions"],
    queryFn: authService.getMyPermissions,
    enabled: open,
  });

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) setIsMaximized(false);
    onOpenChange(nextOpen);
  };

  const permissions = query.data?.permissions ?? [];
  const groups = groupPermissionsByModule(permissions);
  const grantedCount = permissions.filter((p) => p.granted).length;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(
          "flex flex-col overflow-hidden",
          isMaximized
            ? "h-[96vh] w-[98vw] max-w-none"
            : "max-h-[85vh] w-[95vw] max-w-3xl"
        )}
      >
        <button
          type="button"
          onClick={() => setIsMaximized((prev) => !prev)}
          className="absolute right-12 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
          aria-label={isMaximized ? "Restore" : "Maximize"}
        >
          {isMaximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>

        <DialogHeader>
          <DialogTitle>My Permissions</DialogTitle>
        </DialogHeader>

        {query.isError ? (
          <ErrorState message={getApiErrorMessage(query.error, "Failed to load your permissions.")} />
        ) : !query.data ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full rounded-xl" />
            ))}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
              <Avatar className="h-10 w-10">
                <AvatarFallback>{query.data.name.charAt(0).toUpperCase()}</AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{query.data.name}</p>
                <p className="truncate text-xs text-muted-foreground">{query.data.email}</p>
              </div>
              <Badge variant="outline" className="shrink-0">
                {query.data.role}
              </Badge>
              <Badge variant="secondary" className="shrink-0">
                {grantedCount}/{permissions.length} granted
              </Badge>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto pr-1">
              {groups.length === 0 ? (
                <ErrorState message="No permissions found." />
              ) : (
                groups.map(([key, groupPermissions]) => {
                  const Icon = groupIcon(key);
                  const groupGrantedCount = groupPermissions.filter((p) => p.granted).length;

                  return (
                    <div key={key} className="rounded-xl border border-border">
                      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                        <div className="flex items-center gap-2 text-sm font-medium">
                          <Icon className="h-4 w-4 text-primary" />
                          {groupLabel(key)}
                        </div>
                        <Badge variant="secondary">
                          {groupGrantedCount}/{groupPermissions.length}
                        </Badge>
                      </div>
                      <div className="space-y-0.5 p-2">
                        {groupPermissions.map((permission) => (
                          <div
                            key={permission.permission_id}
                            className={cn(
                              "flex items-center gap-3 rounded-lg p-2",
                              !permission.granted && "opacity-50"
                            )}
                          >
                            {permission.granted ? (
                              <Check className="h-4 w-4 shrink-0 text-success" />
                            ) : (
                              <Minus className="h-4 w-4 shrink-0 text-muted-foreground" />
                            )}
                            <span className="flex-1 font-mono text-sm">{permission.permission_name}</span>
                            {permission.granted && permission.source === "override" && (
                              <Badge variant="outline" className="shrink-0 text-xs">
                                Personal Override
                              </Badge>
                            )}
                            {permission.granted && permission.source === "role" && (
                              <Badge variant="outline" className="shrink-0 text-xs">
                                Via Role
                              </Badge>
                            )}
                            {permission.scoped_ticket_ids.length > 0 && (
                              <Badge variant="outline" className="shrink-0 text-xs">
                                Scoped to {permission.scoped_ticket_ids.length} ticket
                                {permission.scoped_ticket_ids.length === 1 ? "" : "s"}
                              </Badge>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
