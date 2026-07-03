import { useState, type ReactNode } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { ToastViewport } from "@/components/common/ToastViewport";

interface AppLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
}

export function AppLayout({ title, description, children }: AppLayoutProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      <Sidebar mobileOpen={mobileNavOpen} onCloseMobile={() => setMobileNavOpen(false)} />
      {/* min-w-0 lets this column shrink below its content's natural
          width — without it, a flex item defaults to min-width: auto,
          so any wide content inside <main> could push the whole
          layout wider than the viewport instead of wrapping/scrolling
          locally. overflow-x-hidden on <main> is the second half of
          that guarantee: nothing in page content can ever create a
          page-level horizontal scrollbar. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar
          title={title}
          description={description}
          onOpenMenu={() => setMobileNavOpen(true)}
        />
        <main className="flex-1 overflow-x-hidden overflow-y-auto scrollbar-thin px-4 py-5 sm:px-7 sm:py-7">
          {children}
        </main>
      </div>
      <ToastViewport />
    </div>
  );
}
