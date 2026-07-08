import { MemoryRouter } from "react-router-dom";
import { ToastProvider } from "@tw/context/ToastContext";
import { ToastViewport } from "@tw/components/common/ToastViewport";
import { CreateMailPage } from "@tw/pages/CreateMailPage";

/**
 * Site Lead's one, deliberately narrow window into the embedded
 * ticket workspace — the dummy-mail simulator, and nothing else.
 *
 * Every other role that reaches the ticket workspace does so through
 * TicketWorkspaceApp's full <BrowserRouter>, which means once
 * mounted, any in-app <Link> (react-router client-side navigation)
 * can move between every ticket-workspace page without Next.js's own
 * router — and therefore this app's own role gate in
 * app/(dashboard)/dashboard/[[...slug]]/page.tsx — ever running
 * again. Site Lead is intentionally excluded from the rest of that
 * SPA (see this repo's CLAUDE.md: "Super Admin, Site Lead, and
 * Viewer instead see RBAC's own admin dashboards"), so mounting the
 * full TicketWorkspaceApp for just this one page would accidentally
 * hand them a client-side escape hatch into every other
 * ticket-workspace route. A <MemoryRouter> instead of a
 * <BrowserRouter> keeps CreateMailPage's own <Link>s (e.g. "View in
 * Inbox" after sending) confined to an in-memory history that never
 * touches the real browser URL, so there's nowhere for it to escape
 * to even if clicked.
 */
export function DummyMailOnlyApp() {
  return (
    <div className="tm-scope">
      <ToastProvider>
        <MemoryRouter initialEntries={["/create-mail"]}>
          <CreateMailPage />
        </MemoryRouter>
        <ToastViewport />
      </ToastProvider>
    </div>
  );
}
