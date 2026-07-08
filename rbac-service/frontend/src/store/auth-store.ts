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
