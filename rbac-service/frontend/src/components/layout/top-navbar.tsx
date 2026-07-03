"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bell,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  Settings as SettingsIcon,
  Shield,
  Sun,
  User,
  UserCircle,
  Users,
} from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useTranslation } from "@/hooks/use-translation";
import { cn } from "@/lib/utils";
import { getVisibleNavItems, NAV_ITEM_TRANSLATION_KEY, NavItemKey } from "@/lib/role-access";
import { authService } from "@/services";
import { getResolvedTheme, useAuthStore, useThemeStore } from "@/store/auth-store";

const SEARCH_INDEX: { title: NavItemKey; href: string; icon: typeof LayoutDashboard }[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Users", href: "/users", icon: Users },
  { title: "Roles", href: "/roles", icon: Shield },
  { title: "Audit Logs", href: "/audit-logs", icon: ClipboardList },
  { title: "Profile", href: "/profile", icon: UserCircle },
  { title: "Settings", href: "/settings", icon: SettingsIcon },
];

interface Notification {
  id: string;
  title: string;
  description: string;
  time: string;
  read: boolean;
}

const INITIAL_NOTIFICATIONS: Notification[] = [
  {
    id: "1",
    title: "New user registered",
    description: "Emma Watts joined the Staff role.",
    time: "5m ago",
    read: false,
  },
  {
    id: "2",
    title: "Role permissions updated",
    description: "Team Lead role permissions were changed.",
    time: "1h ago",
    read: false,
  },
  {
    id: "3",
    title: "Audit log alert",
    description: "Unusual login activity detected for Viewer.",
    time: "3h ago",
    read: true,
  },
];

export function TopNavbar() {
  const router = useRouter();
  const { t } = useTranslation();

  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);

  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [notifications, setNotifications] = useState(INITIAL_NOTIFICATIONS);
  const searchRef = useRef<HTMLDivElement>(null);

  const unreadCount = notifications.filter((n) => !n.read).length;

  const visibleNavItems = useMemo(() => getVisibleNavItems(user?.role), [user?.role]);

  const results = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return SEARCH_INDEX.filter(
      (item) => visibleNavItems.includes(item.title) && item.title.toLowerCase().includes(q)
    );
  }, [query, visibleNavItems]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(event.target as Node)) {
        setSearchOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleLogout = () => {
    authService.logout();
    logout();
    router.push("/login");
  };

  const handleSelectResult = (href: string) => {
    router.push(href);
    setQuery("");
    setSearchOpen(false);
  };

  const markAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  return (
    <header className="sticky top-0 z-30 hidden h-16 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:flex">
      {/* Left Section */}
      <div className="flex items-center gap-4">
        <div ref={searchRef} className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />

          <Input
            placeholder={t("navbar.searchPlaceholder")}
            className="w-72 pl-9"
            value={query}
            onFocus={() => setSearchOpen(true)}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && results.length > 0) {
                handleSelectResult(results[0].href);
              }
              if (e.key === "Escape") {
                setSearchOpen(false);
              }
            }}
          />

          <AnimatePresence>
            {searchOpen && query.trim() && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
                className="absolute left-0 top-full z-40 mt-2 w-72 overflow-hidden rounded-xl border border-border bg-popover p-1.5 shadow-lg"
              >
                {results.length === 0 ? (
                  <p className="px-3 py-4 text-center text-sm text-muted-foreground">
                    {t("navbar.noResults", { query })}
                  </p>
                ) : (
                  results.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.href}
                        onClick={() => handleSelectResult(item.href)}
                        className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
                      >
                        <Icon className="h-4 w-4 text-muted-foreground" />
                        {t(NAV_ITEM_TRANSLATION_KEY[item.title])}
                      </button>
                    );
                  })
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Right Section */}
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          aria-label="Toggle theme"
        >
          {getResolvedTheme(theme) === "dark" ? (
            <Sun className="h-5 w-5" />
          ) : (
            <Moon className="h-5 w-5" />
          )}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="relative" aria-label={t("navbar.notifications")}>
              <Bell className="h-5 w-5" />
              {unreadCount > 0 && (
                <span className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
                  {unreadCount}
                </span>
              )}
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-80">
            <div className="flex items-center justify-between px-2 py-1.5">
              <DropdownMenuLabel className="p-0 text-sm">{t("navbar.notifications")}</DropdownMenuLabel>
              {unreadCount > 0 && (
                <button
                  onClick={markAllRead}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  {t("navbar.markAllRead")}
                </button>
              )}
            </div>
            <DropdownMenuSeparator />

            {notifications.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                {t("navbar.allCaughtUp")}
              </p>
            ) : (
              notifications.map((notification) => (
                <DropdownMenuItem
                  key={notification.id}
                  className="flex-col items-start gap-0.5 py-2"
                >
                  <div className="flex w-full items-center gap-2">
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        notification.read ? "bg-transparent" : "bg-primary"
                      )}
                    />
                    <span className="text-sm font-medium">{notification.title}</span>
                  </div>
                  <p className="pl-3.5 text-xs text-muted-foreground">
                    {notification.description}
                  </p>
                  <p className="pl-3.5 text-[11px] text-muted-foreground/70">
                    {notification.time}
                  </p>
                </DropdownMenuItem>
              ))
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-3 pl-2 pr-3">
              <Avatar className="h-9 w-9">
                <AvatarFallback>
                  {user?.name?.charAt(0).toUpperCase() ?? "M"}
                </AvatarFallback>
              </Avatar>

              <div className="hidden text-left md:block">
                <p className="text-sm font-medium leading-none">
                  {user?.name ?? "Manager"}
                </p>

                <p className="mt-1 text-xs text-muted-foreground">
                  {user?.role ?? "Manager"}
                </p>
              </div>
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>{t("navbar.myAccount")}</DropdownMenuLabel>
            <DropdownMenuSeparator />

            <DropdownMenuItem asChild>
              <Link href="/profile">
                <User className="mr-2 h-4 w-4" />
                {t("nav.profile")}
              </Link>
            </DropdownMenuItem>

            <DropdownMenuItem asChild>
              <Link href="/settings">
                <SettingsIcon className="mr-2 h-4 w-4" />
                {t("nav.settings")}
              </Link>
            </DropdownMenuItem>

            <DropdownMenuSeparator />

            <DropdownMenuItem
              onClick={handleLogout}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="mr-2 h-4 w-4" />
              {t("nav.logout")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
