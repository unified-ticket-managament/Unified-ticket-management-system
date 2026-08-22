import { create } from "zustand";
import { persist } from "zustand/middleware";

import { getStoredTokens, setTokens } from "@/lib/api";
import { impersonationService } from "@/services";
import { AuthUser } from "@/types";

interface ImpersonationState {
  isImpersonating: boolean;
  targetName: string | null;
  targetRole: string | null;
  expiresAt: string | null;
  // The admin's own tokens, snapshotted right before the token cache
  // is swapped to the impersonation pair — restored verbatim on Exit.
  // Persisted (not just in-memory) so a page refresh mid-impersonation
  // doesn't strand the admin without a way back to their own session.
  actorTokens: { access: string; refresh: string } | null;
  actorUser: AuthUser | null;

  // Both actions swap tokens then hard-navigate (window.location, not
  // a Next.js client-side route change) — this app has several
  // session-scoped caches (the notification bell's long-lived
  // EventSource, React Query's identity-unscoped cache keys, the
  // embedded ticket workspace's WorkflowContext "once per session"
  // fetches) that only reliably reset on a full page load, not a
  // Zustand store update. See root CLAUDE.md's impersonation plan for
  // the full rationale — this is deliberately simpler than manually
  // invalidating each of those caches.
  startImpersonation: (
    targetUserId: string,
    currentUser: AuthUser | null
  ) => Promise<void>;
  endImpersonation: () => Promise<void>;
}

export const useImpersonationStore = create<ImpersonationState>()(
  persist(
    (set, get) => ({
      isImpersonating: false,
      targetName: null,
      targetRole: null,
      expiresAt: null,
      actorTokens: null,
      actorUser: null,

      startImpersonation: async (targetUserId, currentUser) => {
        const { access, refresh } = getStoredTokens();

        if (!access || !refresh) {
          throw new Error("You must be logged in to start impersonation.");
        }

        const response = await impersonationService.start(targetUserId);

        set({
          isImpersonating: true,
          targetName: response.target_user.name,
          targetRole: response.target_user.role,
          expiresAt: response.expires_at,
          actorTokens: { access, refresh },
          actorUser: currentUser,
        });

        setTokens(response.access_token, response.refresh_token);
        window.location.href = "/dashboard";
      },

      endImpersonation: async () => {
        const { actorTokens } = get();

        try {
          await impersonationService.end();
        } catch {
          // Best-effort — the session may have already expired
          // server-side; the admin's own tokens are restored either
          // way below.
        }

        if (actorTokens) {
          setTokens(actorTokens.access, actorTokens.refresh);
        }

        set({
          isImpersonating: false,
          targetName: null,
          targetRole: null,
          expiresAt: null,
          actorTokens: null,
          actorUser: null,
        });

        window.location.href = "/dashboard";
      },
    }),
    {
      name: "impersonation-storage",
    }
  )
);
