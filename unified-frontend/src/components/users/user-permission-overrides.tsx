"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { KeyRound, Loader2, ShieldCheck, X } from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import { permissionOverrideService } from "@/services";
import { Permission, PermissionOverride, User } from "@/types";

interface UserPermissionOverridesProps {
  user: User;
  roleName: string;
  rolePermissions: Permission[];
  allPermissions: Permission[];
  enabled: boolean;
}

export function UserPermissionOverrides({
  user,
  roleName,
  rolePermissions,
  allPermissions,
  enabled,
}: UserPermissionOverridesProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [selectedPermissionId, setSelectedPermissionId] = useState("");
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  const overridesQuery = useQuery({
    queryKey: ["permission-overrides", user.user_id],
    queryFn: () => permissionOverrideService.list(user.user_id),
    enabled,
  });

  const overrides: PermissionOverride[] = overridesQuery.data ?? [];

  // Only permissions the role doesn't already grant are offered here —
  // an override only ever adds capability beyond the role, so a
  // redundant choice should never even appear in this list (the API
  // rejects it too, this just keeps the UI honest about that).
  const grantablePermissions = useMemo(() => {
    const roleIds = new Set(rolePermissions.map((p) => p.permission_id));
    const activeOverrideIds = new Set(overrides.map((o) => o.permission_id));
    return allPermissions.filter(
      (p) => !roleIds.has(p.permission_id) && !activeOverrideIds.has(p.permission_id)
    );
  }, [allPermissions, rolePermissions, overrides]);

  const grantMutation = useMutation({
    mutationFn: () =>
      permissionOverrideService.grant(user.user_id, {
        permission_id: selectedPermissionId,
        reason: reason.trim() || undefined,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["permission-overrides", user.user_id] });
      setSelectedPermissionId("");
      setReason("");
      setExpiresAt("");
      toast({
        title: "Permission granted",
        description: `${user.name} now has this permission personally — the ${roleName} role is unchanged.`,
      });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to grant permission",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (overrideId: string) =>
      permissionOverrideService.revoke(user.user_id, overrideId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["permission-overrides", user.user_id] });
      toast({ title: "Permission revoked" });
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      toast({
        variant: "destructive",
        title: "Failed to revoke permission",
        description: error.response?.data?.detail ?? "Please try again.",
      });
    },
  });

  return (
    <PermissionGuard permission="permission:override_grant" fallback={null}>
      <div className="mt-6 rounded-xl border border-border p-4">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">
            Personal Permission Grants — {user.name} only
          </h3>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          These grants apply only to this person and never change the {roleName} role
          or anyone else who holds it.
        </p>

        {overridesQuery.isLoading ? (
          <Skeleton className="mt-3 h-16 w-full rounded-lg" />
        ) : overrides.length === 0 ? (
          <p className="mt-3 text-xs text-muted-foreground">
            No personal grants yet.
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {overrides.map((override) => (
              <div
                key={override.override_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 p-2.5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <KeyRound className="h-3.5 w-3.5 shrink-0 text-primary" />
                    <span className="truncate font-mono text-xs">
                      {override.permission_name}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Granted {formatDate(override.granted_at)}
                    {override.reason ? ` — ${override.reason}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge variant={override.expires_at ? "outline" : "secondary"}>
                    {override.expires_at
                      ? `Expires ${formatDate(override.expires_at)}`
                      : "Never expires"}
                  </Badge>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    disabled={revokeMutation.isPending}
                    onClick={() => revokeMutation.mutate(override.override_id)}
                    aria-label={`Revoke ${override.permission_name}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 space-y-3 border-t border-border pt-3">
          <div>
            <Label className="text-xs">Grant a permission</Label>
            <Select value={selectedPermissionId} onValueChange={setSelectedPermissionId}>
              <SelectTrigger className="mt-1">
                <SelectValue
                  placeholder={
                    grantablePermissions.length === 0
                      ? "This user already has every available permission"
                      : "Select a permission"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {grantablePermissions.map((permission) => (
                  <SelectItem key={permission.permission_id} value={permission.permission_id}>
                    {permission.permission_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Reason (optional)</Label>
              <Input
                className="mt-1"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why this exception?"
              />
            </div>
            <div>
              <Label className="text-xs">Expires (optional)</Label>
              <Input
                type="date"
                className="mt-1"
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
              />
            </div>
          </div>

          <Button
            type="button"
            size="sm"
            disabled={!selectedPermissionId || grantMutation.isPending}
            onClick={() => grantMutation.mutate()}
          >
            {grantMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Grant Permission
          </Button>
        </div>
      </div>
    </PermissionGuard>
  );
}
