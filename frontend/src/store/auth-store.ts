import { create } from "zustand";
import { persist } from "zustand/middleware";

import { AuthUser } from "@/types";

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  setUser: (user: AuthUser | null) => void;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (permissions: string[]) => boolean;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      setUser: (user) => set({ user, isAuthenticated: !!user }),
      hasPermission: (permission) => {
        const { user } = get();
        const permissions = user?.permissions ?? [];
        return permissions.includes(permission);
      },
      hasAnyPermission: (permissions) => {
        const { user } = get();
        if (!user) {
          return false;
        }
        const userPermissions = user.permissions ?? [];
        return permissions.some((p) =>
          userPermissions.includes(p)
        );
      },
      logout: () => set({ user: null, isAuthenticated: false }),
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({ user: state.user, isAuthenticated: state.isAuthenticated }),
    }
  )
);

export type Theme = "light" | "dark" | "system";

export function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function getResolvedTheme(theme: Theme): "light" | "dark" {
  return theme === "system" ? getSystemTheme() : theme;
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", getResolvedTheme(theme) === "dark");
}

interface ThemeState {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: "dark",
      toggleTheme: () => {
        const next = getResolvedTheme(get().theme) === "dark" ? "light" : "dark";
        set({ theme: next });
        applyTheme(next);
      },
      setTheme: (theme) => {
        set({ theme });
        applyTheme(theme);
      },
    }),
    { name: "theme-storage" }
  )
);
