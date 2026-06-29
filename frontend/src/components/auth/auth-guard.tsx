"use client";

import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { user, setUser, isAuthenticated } = useAuthStore();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.replace("/login");
      return;
    }

    if (!user) {
      authService
        .me()
        .then(setUser)
        .catch(() => {
          router.replace("/login");
        });
    }
  }, [user, setUser, router]);

  if (!isAuthenticated || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="w-full max-w-md space-y-4">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return <DashboardShell>{children}</DashboardShell>;
}
