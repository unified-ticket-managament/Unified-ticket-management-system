import { create } from "zustand";
import { persist } from "zustand/middleware";

import { AuthUser } from "@/types";

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  setUser: (user: AuthUser | null) => void;
  refreshUser: (user: AuthUser) => void;
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
      // A background `/auth/me` refetch (re-checking Reply-external
      // permission, saving Profile/Settings, opening a ticket's Internal
      // Note tab, etc.) must never clobber the Mail 3-panel divider
      // widths — MailWorkspaceLayout.tsx exclusively owns those two
      // fields and persists them itself via its own drag-driven PATCH.
      // If one of those unrelated refetches resolves while a divider
      // drag's own save is still in flight, a plain full-object setUser
      // would silently revert the just-dragged width back to the
      // fetched (pre-drag) value. refreshUser replaces every other
      // field from the fresh fetch but always keeps whichever width the
      // store already holds.
      refreshUser: (user) =>
        set((state) => ({
          user: state.user
            ? {
                ...user,
                mail_inbox_folder_width: state.user.mail_inbox_folder_width,
                mail_inbox_list_width: state.user.mail_inbox_list_width,
              }
            : user,
          isAuthenticated: true,
        })),
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
