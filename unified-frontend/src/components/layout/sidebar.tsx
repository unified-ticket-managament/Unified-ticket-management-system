"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  BarChart3,
  ChevronsLeft,
  ChevronsRight,
  ClipboardList,
  History,
  Inbox,
  KeyRound,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Network,
  Shield,
  Ticket,
  Timer,
  UserCircle,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslation } from "@/hooks/use-translation";
import { cn } from "@/lib/utils";
import { canSeeNavItem, NAV_ITEM_TRANSLATION_KEY, NavItemKey } from "@/lib/role-access";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";
import { useSettingsStore } from "@/store/settings-store";

// Every role except Viewer lands on the embedded Ticket Management
// workspace at /dashboard (see role-access.ts) — these items route
// there via Next's own router (plain internal hrefs), not an external
// link, since the workspace is now part of this same app.
const menuItems: {
  title: NavItemKey;
  href: string;
  icon: typeof LayoutDashboard;
}[] = [
  {
    title: "Dashboard",
    href: "/dashboard",
    icon: LayoutDashboard,
  },
  {
    title: "All Tickets",
    href: "/all-tickets",
    icon: Ticket,
  },
  {
    title: "My Tickets",
    href: "/my-tickets",
    icon: ClipboardList,
  },
  {
    title: "Users",
    href: "/users",
    icon: Users,
  },
  {
    title: "Roles",
    href: "/roles",
    icon: Shield,
  },
  {
    title: "Reports",
    href: "/reports",
    icon: BarChart3,
  },
  {
    title: "Inbox",
    href: "/dashboard/inbox",
    icon: Inbox,
  },
  {
    title: "Interactions",
    href: "/dashboard/interactions",
    icon: MessageSquare,
  },
  {
    title: "Tickets",
    href: "/dashboard/tickets",
    icon: Ticket,
  },
  {
    title: "Ticket Audit Log",
    href: "/dashboard/audit-logs",
    icon: History,
  },
  {
    title: "SLA Timing Matrix",
    href: "/settings/sla-timing-matrix",
    icon: Timer,
  },
  {
    title: "Reporting Managers",
    href: "/settings/reporting-managers",
    icon: Network,
  },
  {
    title: "Permission Requests",
    href: "/permission-requests",
    icon: KeyRound,
  },
  {
    title: "Profile",
    href: "/profile",
    icon: UserCircle,
  },
];

// Drag-to-resize bounds for the expanded main sidebar (collapsed state
// stays a fixed 80px, unaffected). 220 keeps room for this app's
// longest nav labels ("SLA Timing Matrix", "Reporting Managers") before
// they fall back to the existing truncate behavior; 400 is generous
// without letting the sidebar dominate the viewport. Brackets both
// existing known-good widths: the default (256) and the mobile drawer's
// own fixed width (288, SheetContent's w-72).
const MIN_SIDEBAR_WIDTH = 220;
const MAX_SIDEBAR_WIDTH = 400;

function clampSidebarWidth(width: number) {
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width));
}

interface SidebarContentProps {
  collapsed?: boolean;
  onNavigate?: () => void;
}

export function SidebarContent({ collapsed = false, onNavigate }: SidebarContentProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useTranslation();
  const logout = useAuthStore((state) => state.logout);
  const role = useAuthStore((state) => state.user?.role);

  const handleLogout = () => {
    authService.logout();
    logout();
    router.push("/login");
  };

  // "/dashboard" is a prefix of every ticket-workspace route
  // ("/dashboard/tickets", "/dashboard/inbox", ...), so it needs an
  // exact match rather than the usual prefix match — otherwise the
  // Dashboard item would stay highlighted no matter which workspace
  // page is actually open.
  const isActive = (href: string) =>
    href === "/dashboard"
      ? pathname === href
      : pathname === href || pathname.startsWith(`${href}/`);

  const visibleItems = menuItems.filter((item) => canSeeNavItem(role, item.title));

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-full flex-col bg-card">
        {/* Logo */}
        <div className={cn("flex items-center gap-3 border-b border-border px-6 py-5", collapsed && "justify-center px-3")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Shield className="h-5 w-5" />
          </div>

          {!collapsed && (
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold tracking-tight">UTMS</h1>
              <p className="truncate text-xs text-muted-foreground">Unified Ticket Management System</p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-5">
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            const label = t(NAV_ITEM_TRANSLATION_KEY[item.title]);

            const buttonContent = (
              <Button
                variant="ghost"
                className={cn(
                  "relative w-full gap-3 font-medium text-muted-foreground hover:text-foreground",
                  collapsed ? "justify-center px-0" : "justify-start",
                  active && "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
                )}
              >
                {active && (
                  <motion.span
                    layoutId="sidebar-active-indicator"
                    className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary"
                    transition={{ type: "spring", stiffness: 350, damping: 30 }}
                  />
                )}
                <Icon className="h-5 w-5 shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </Button>
            );

            const link = (
              <Link key={item.href} href={item.href} onClick={onNavigate}>
                {buttonContent}
              </Link>
            );

            if (!collapsed) return link;

            return (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{link}</TooltipTrigger>
                <TooltipContent side="right">{label}</TooltipContent>
              </Tooltip>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-border p-3">
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  className="w-full justify-center px-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={handleLogout}
                >
                  <LogOut className="h-5 w-5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">{t("nav.logout")}</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              className="w-full justify-start gap-3 text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={handleLogout}
            >
              <LogOut className="h-5 w-5" />
              {t("nav.logout")}
            </Button>
          )}
        </div>
      </div>
    </TooltipProvider>
  );
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);

  const persistedWidth = useSettingsStore((s) => s.sidebarWidth);
  const setPersistedWidth = useSettingsStore((s) => s.setSidebarWidth);
  const clampedPersistedWidth = clampSidebarWidth(persistedWidth);

  // Non-null only while a drag is in progress — live pointermove
  // updates stay local (drive the render), and only the final value
  // on pointerup is written to the persisted store, so dragging never
  // hammers localStorage.
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const dragWidthRef = useRef<number | null>(null);
  const dragStartRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const cleanupRef = useRef<() => void>(() => {});

  const isDragging = dragWidth !== null;
  const effectiveWidth = dragWidth ?? clampedPersistedWidth;

  const handlePointerMove = useCallback((event: PointerEvent) => {
    const drag = dragStartRef.current;
    if (!drag) return;
    const next = clampSidebarWidth(drag.startWidth + (event.clientX - drag.startX));
    dragWidthRef.current = next;
    setDragWidth(next);
  }, []);

  // A stable callback (so it can be added/removed as the same function
  // reference) can't safely close over fresh `dragWidth` state — reads
  // the ref instead, which handlePointerMove keeps current.
  const endDrag = useCallback(() => {
    if (dragWidthRef.current !== null) {
      setPersistedWidth(dragWidthRef.current);
    }
    dragStartRef.current = null;
    dragWidthRef.current = null;
    setDragWidth(null);
    cleanupRef.current();
    cleanupRef.current = () => {};
  }, [setPersistedWidth]);

  const beginDrag = useCallback(
    (event: React.PointerEvent) => {
      event.preventDefault();
      dragStartRef.current = { startX: event.clientX, startWidth: clampedPersistedWidth };
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", endDrag);
      cleanupRef.current = () => {
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", endDrag);
      };
    },
    [clampedPersistedWidth, handlePointerMove, endDrag]
  );

  // Safety net for unmounting mid-drag — same convention
  // MailWorkspaceLayout's own resizable panels already use.
  useEffect(() => () => endDrag(), [endDrag]);

  return (
    <motion.aside
      animate={{ width: collapsed ? 80 : effectiveWidth }}
      transition={isDragging ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 32 }}
      className="relative h-screen shrink-0 border-r border-border print:hidden"
    >
      <SidebarContent collapsed={collapsed} />

      {!collapsed && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          onPointerDown={beginDrag}
          className={cn(
            "absolute right-0 top-0 z-0 h-full w-1.5 cursor-col-resize touch-none select-none",
            "after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent after:transition-colors",
            "hover:after:bg-primary/50",
            isDragging && "after:bg-primary/60"
          )}
        />
      )}

      <Button
        variant="outline"
        size="icon"
        className="absolute -right-3.5 top-20 z-10 h-7 w-7 rounded-full bg-background shadow-sm"
        onClick={() => setCollapsed((prev) => !prev)}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronsRight className="h-3.5 w-3.5" /> : <ChevronsLeft className="h-3.5 w-3.5" />}
      </Button>
    </motion.aside>
  );
}
