import type { ReactNode } from "react";
import { PageHeader } from "@/components/layout/dashboard-shell";

interface AppLayoutProps {
  title?: string;
  description?: string;
  children: ReactNode;
}

// Drop-in replacement for the standalone Ticketing app's AppLayout —
// same props, so none of the copied pages need to change. RBAC's own
// DashboardLayout (rendered one level up, outside the embedded router)
// already provides the Sidebar/Topbar chrome; this only renders the
// per-page title bar, reusing RBAC's own PageHeader component instead
// of duplicating one.
//
// Deliberately does NOT re-apply the `tm-scope` class — that's already
// set once at the TicketWorkspaceApp root. Re-declaring it here would
// re-trigger `.tm-scope`'s base CSS-variable declarations on this
// inner element, which (per normal CSS cascade) always wins over an
// inherited value from an ancestor — silently overriding the
// `.tm-unified-theme` remap on every single page.
// `title` is optional so a page (e.g. Mail) can opt out of the title
// bar entirely — omitting it renders no PageHeader at all, not one
// with an empty heading, so no leftover margin/whitespace is left
// behind where the header used to be.
export function AppLayout({ title, description, children }: AppLayoutProps) {
  return (
    <div>
      {title && <PageHeader title={title} description={description} />}
      {children}
    </div>
  );
}
