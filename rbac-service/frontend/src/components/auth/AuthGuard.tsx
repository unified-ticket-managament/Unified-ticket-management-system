"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

interface Props {
  children: ReactNode;
}

export function AuthGuard({ children }: Props) {
  const router = useRouter();

  const setUser = useAuthStore((state) => state.setUser);

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const initialize = async () => {
      const token = localStorage.getItem("access_token");

      if (!token) {
        router.replace("/login");
        return;
      }

      try {
        const me = await authService.me();

        if (!cancelled) {
          setUser(me);
          setLoading(false);
        }
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        router.replace("/login");
      }
    };

    initialize();

    return () => {
      cancelled = true;
    };
  }, [router, setUser]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="w-full max-w-md space-y-4">
          <Skeleton className="h-8 w-40" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return <DashboardShell>{children}</DashboardShell>;
}
