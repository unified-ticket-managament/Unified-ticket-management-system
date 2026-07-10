import { useAuthStore } from "@/store/auth-store";
import type { CurrentUser } from "@tw/types";

// Adapter for the embedded ticket workspace: RBAC's own AuthGuard has
// already authenticated the user by the time any of this renders, so
// there's no separate login/session here — this just re-exposes RBAC's
// already-resolved identity (from `useAuthStore`) under the same
// `useAuthContext()` shape the copied Ticketing pages already expect.
// RBAC's `AuthUser` and Ticketing's `CurrentUser` have always had the
// same fields (both mirror the same `/auth/me` response), so no mapping
// is needed beyond the type alias.
export function useAuthContext(): {
  currentUser: CurrentUser | null;
  isLoading: boolean;
} {
  const user = useAuthStore((state) => state.user);
  return { currentUser: user, isLoading: false };
}
