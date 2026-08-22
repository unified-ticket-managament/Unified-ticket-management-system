"use client";

import { ShieldAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useImpersonationStore } from "@/store/impersonation-store";

// The one persistent, always-visible indicator that the current
// session isn't a normal login — see root CLAUDE.md's impersonation
// plan's "Do not make the impersonated session visually
// indistinguishable from a normal login" requirement. No existing
// persistent-banner component exists in this app to reuse (checked);
// styled with the same `bg-warning/10 text-warning` tone convention
// components/shared/stats.tsx's StatCard already uses for its
// "warning" tone, rather than inventing a new color.
export function ImpersonationBanner() {
  const isImpersonating = useImpersonationStore((s) => s.isImpersonating);
  const targetName = useImpersonationStore((s) => s.targetName);
  const targetRole = useImpersonationStore((s) => s.targetRole);
  const endImpersonation = useImpersonationStore((s) => s.endImpersonation);
  const [ending, setEnding] = useState(false);

  if (!isImpersonating) {
    return null;
  }

  const handleExit = async () => {
    setEnding(true);
    try {
      await endImpersonation();
    } finally {
      setEnding(false);
    }
  };

  return (
    <div className="flex shrink-0 items-center justify-between gap-3 border-b border-warning/30 bg-warning/10 px-4 py-2 text-sm text-warning print:hidden">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 shrink-0" />
        <span>
          Impersonating <strong>{targetName}</strong>
          {targetRole ? ` (${targetRole})` : ""}
        </span>
      </div>
      <Button
        variant="outline"
        size="sm"
        className="h-7 border-warning/40 text-warning hover:bg-warning/20"
        onClick={handleExit}
        disabled={ending}
      >
        {ending ? "Exiting..." : "Exit Impersonation"}
      </Button>
    </div>
  );
}
