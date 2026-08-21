"use client";

import { useEffect, useState } from "react";

// Mail-specific: decides between the Outlook-style three-panel
// workspace (desktop) and the original single-pane-swap layout
// (mobile/tablet) — see InboxPage.tsx. Matches Tailwind's own `lg`
// breakpoint (1024px) so the switch lines up with every other `lg:`
// class already used throughout the ticket workspace.
const DESKTOP_QUERY = "(min-width: 1024px)";

export function useIsDesktopViewport(): boolean {
  // The whole ticket workspace only ever renders client-side (see
  // TicketWorkspaceApp's own next/dynamic(..., { ssr: false })), so
  // reading `window` in the initializer here can never mismatch a
  // server-rendered pass.
  const [isDesktop, setIsDesktop] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.matchMedia(DESKTOP_QUERY).matches : true
  );

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_QUERY);
    const handleChange = () => setIsDesktop(mql.matches);
    handleChange();
    mql.addEventListener("change", handleChange);
    return () => mql.removeEventListener("change", handleChange);
  }, []);

  return isDesktop;
}
