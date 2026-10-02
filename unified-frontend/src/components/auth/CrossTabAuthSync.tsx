"use client";

import { useEffect } from "react";

import { registerCrossTabAuthSync } from "@/lib/cross-tab-auth-sync";

// Renders nothing — just keeps the cross-tab logout/impersonation
// listener alive for the lifetime of the app. Mounted once at the app
// root (src/app/layout.tsx) so it covers every route, not just the
// authenticated dashboard group.
export function CrossTabAuthSync() {
  useEffect(() => registerCrossTabAuthSync(), []);

  return null;
}
