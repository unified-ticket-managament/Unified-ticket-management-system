"use client";

import { Shield } from "lucide-react";

// Thin, purely decorative left-most strip (Outlook-web-style "app bar")
// sitting beside the existing named Sidebar — brand mark only, no
// items, no routing, no permission logic. The real navigation stays
// entirely in Sidebar/SidebarContent, unchanged.
export function IconRail() {
  return (
    <div className="flex h-screen w-14 flex-none flex-col items-center gap-4 border-r border-border bg-card py-4 print:hidden">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Shield className="h-5 w-5" />
      </div>
    </div>
  );
}
