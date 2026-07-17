"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { DashboardShell } from "@/components/layout/dashboard-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { isSupportedLanguage } from "@/lib/i18n/translations";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useSettingsStore } from "@/store/settings-store";

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

          // The user's saved language preference lives on the `users`
          // table now (User.language — see shared_models.models.User),
          // not just this device's local settings-storage copy. Sync
          // it into the settings store on every load so a language
          // saved from one device/browser applies on any other, and
          // survives a fresh cold load without relying on localStorage
          // alone.
          if (isSupportedLanguage(me.language)) {
            useSettingsStore.getState().setLanguage(me.language);
          }

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
