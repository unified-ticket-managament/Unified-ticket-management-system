"use client";

import { ReactNode } from "react";

import { useAuthStore } from "@/store/auth-store";

interface PermissionGuardProps {
  permission?: string;
  permissions?: string[];
  requireAll?: boolean;
  fallback?: ReactNode;
  children: ReactNode;
}

export function PermissionGuard({
  permission,
  permissions = [],
  requireAll = false,
  fallback = null,
  children,
}: PermissionGuardProps) {
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const hasAnyPermission = useAuthStore((s) => s.hasAnyPermission);

  const required = permission ? [permission, ...permissions] : permissions;

  if (required.length === 0) {
    return <>{children}</>;
  }

  const allowed = requireAll
    ? required.every((p) => hasPermission(p))
    : hasAnyPermission(required);

  return allowed ? <>{children}</> : <>{fallback}</>;
}
