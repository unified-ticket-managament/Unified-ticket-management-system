"use client";

import { useAuthStore } from "@/store/auth-store";

export function usePermissions() {
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const hasAnyPermission = useAuthStore((s) => s.hasAnyPermission);
  const user = useAuthStore((s) => s.user);

  return { hasPermission, hasAnyPermission, user, permissions: user?.permissions ?? [] };
}

export function useAuth() {
  const user = useAuthStore((s) => s.user);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);

  return { user, isAuthenticated, setUser, logout };
}
