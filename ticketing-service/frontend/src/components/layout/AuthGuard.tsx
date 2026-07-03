import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuthContext } from "@/context/AuthContext";

// Gates every route below it on a resolved, real RBAC identity —
// replaces the old no-auth-at-all state where any agent_name string
// was trusted at face value.
export function AuthGuard({ children }: { children: ReactNode }) {
  const { currentUser, isLoading } = useAuthContext();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <span className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </div>
    );
  }

  if (!currentUser) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
