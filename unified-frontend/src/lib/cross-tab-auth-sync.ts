import { clearTokens } from "@/lib/api";

// The native `storage` event only ever fires in OTHER tabs of the same
// origin, never the tab that made the write — exactly the signal needed
// here, no BroadcastChannel required. Only two keys are security-critical
// enough to force a reaction in an otherwise-idle tab: logging out
// (`access_token` removed) and starting/ending impersonation
// (`impersonation-storage` changed). Every other persisted key
// (settings-storage, profile-extras-storage, auth-storage's non-auth
// fields) is a user preference that should just apply on this tab's next
// natural read, not force a reload — see impersonation-store.ts's own
// comment on why only these session-identity-changing actions need a hard
// reset.
export function registerCrossTabAuthSync(): () => void {
  const handleStorage = (event: StorageEvent) => {
    if (event.storageArea !== window.localStorage) {
      return;
    }

    if (event.key === "access_token" && event.newValue === null) {
      clearTokens();
      if (!window.location.pathname.includes("/login")) {
        window.location.href = "/login";
      }
      return;
    }

    if (event.key === "impersonation-storage") {
      if (!window.location.pathname.includes("/login")) {
        window.location.reload();
      }
    }
  };

  window.addEventListener("storage", handleStorage);
  return () => window.removeEventListener("storage", handleStorage);
}
