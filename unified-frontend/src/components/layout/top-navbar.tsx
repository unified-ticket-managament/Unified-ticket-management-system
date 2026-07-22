"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, LogOut, User, X } from "lucide-react";

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
import { useTranslation } from "@/hooks/use-translation";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import {
  getNotifications,
  getNotificationStreamUrl,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/lib/notifications-api";
import { authService } from "@/services";
import { useAuthStore } from "@/store/auth-store";

// Reconnect backoff for the notification SSE connection — doubles
// each consecutive failure, capped at 30s, reset back to the base on
// any successful open. Deliberately unbounded in attempt count (kept
// trying forever while this component is mounted): a network blip or
// a backend restart should silently self-heal without the bell ever
// needing a manual page refresh.
const SSE_RECONNECT_BASE_DELAY_MS = 1_000;
const SSE_RECONNECT_MAX_DELAY_MS = 30_000;

// SLA_AT_RISK/SLA_BREACHED/SLA_ESCALATED (app/notifications/service.py's
// NotificationType) — colored distinctly from the generic unread dot so
// severity reads at a glance, matching the same tier colors used on the
// Ticket Detail page's SLA card/badge.
const SLA_NOTIFICATION_DOT: Record<string, string> = {
  SLA_AT_RISK: "bg-warning",
  SLA_BREACHED: "bg-danger",
  SLA_ESCALATED: "bg-danger",
};

// Every notification `link` the backend generates (see
// unified-backend/app/notifications/service.py's `notify()` call sites)
// is written as if the ticket workspace were mounted at the app root —
// "/tickets/{id}", "/inbox" — because that's where it lives in the
// standalone ticketing-service frontend. In this unified app, that same
// page tree is instead mounted under react-router's basename="/dashboard"
// (see TicketWorkspaceApp.tsx), so pushing the raw link 404s: there is no
// top-level Next.js route for "/tickets" or "/inbox". This prefixes only
// the paths that actually belong to that embedded subtree, leaving
// RBAC-native root links (e.g. "/permission-requests") untouched.
const TICKET_WORKSPACE_ROUTES = ["/tickets", "/inbox", "/interactions", "/create-mail", "/audit-logs"];

function resolveNotificationHref(link: string | null): string | null {
  if (!link) return null;
  const isTicketWorkspaceRoute = TICKET_WORKSPACE_ROUTES.some(
    (route) =>
      link === route || link.startsWith(`${route}/`) || link.startsWith(`${route}?`)
  );
  return isTicketWorkspaceRoute ? `/dashboard${link}` : link;
}

function timeAgo(isoString: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function TopNavbar() {
  const router = useRouter();
  const { t } = useTranslation();
  const { toast } = useToast();

  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  // Derived, not separately tracked — a single source of truth means
  // every update path (SSE arrival, mark-read, mark-all-read, local
  // dismiss) automatically keeps the badge correct with no hand-sync.
  // Previously this was its own useState, independently decremented in
  // three different places (mark-all-read, click-to-read, dismiss) —
  // real duplicated bookkeeping that only stayed correct by each of
  // those call sites remembering to update it too.
  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.is_read).length,
    [notifications]
  );

  // The backend has no delete/dismiss endpoint for notifications, so
  // "Clear All" / removing a single notification is a client-side-only
  // dismissal — ids the user has removed are tracked here and filtered
  // back out of every subsequent poll, otherwise a dismissed
  // notification would silently reappear on the next 30s refresh.
  const dismissedIdsRef = useRef<Set<string>>(new Set());

  // Every notification_id already delivered, so a genuinely duplicate
  // push (a defensive guard, not an expected occurrence — each open
  // connection is pushed to exactly once per notify() call) never
  // double-inserts or double-toasts.
  const seenIdsRef = useRef<Set<string>>(new Set());

  // One-time hydration on mount: SSE only pushes *new* events going
  // forward, it never replays history, so the initial list/badge still
  // needs one ordinary fetch to seed state. Silent on failure, same
  // rationale as before — the bell just starts empty until the next
  // real-time event rather than showing an error.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const data = await getNotifications();
        if (cancelled) return;

        seenIdsRef.current = new Set(data.items.map((n) => n.notification_id));
        const visible = data.items.filter(
          (n) => !dismissedIdsRef.current.has(n.notification_id)
        );
        setNotifications(visible);
      } catch {
        // ignore — the SSE connection below still delivers new events
        // even if this initial hydration failed.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Real-time delivery via Server-Sent Events — replaces the old 30s
  // GET /notifications poll entirely. One EventSource per mount (this
  // component itself only mounts once per authenticated session, see
  // DashboardLayout — it sits outside the per-navigation animation
  // wrapper), manually reconnected with exponential backoff on error
  // since the native EventSource auto-reconnect doesn't reliably retry
  // after every failure mode and gives no control over backoff pacing.
  useEffect(() => {
    let cancelled = false;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let attempt = 0;

    function scheduleReconnect() {
      if (cancelled) return;
      const delay = Math.min(
        SSE_RECONNECT_BASE_DELAY_MS * 2 ** attempt,
        SSE_RECONNECT_MAX_DELAY_MS
      );
      attempt += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    }

    function handleNotificationEvent(event: MessageEvent) {
      let payload: { notification: NotificationItem };
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }
      const n = payload.notification;
      if (!n || seenIdsRef.current.has(n.notification_id)) return;
      seenIdsRef.current.add(n.notification_id);

      // SLA breach/at-risk/escalation notifications get a toast in
      // addition to the bell update — everything else (permission
      // requests, etc.) only updates the bell, unchanged from before.
      if (n.notification_type in SLA_NOTIFICATION_DOT) {
        toast({
          variant: n.notification_type === "SLA_AT_RISK" ? "default" : "destructive",
          title: n.title,
          description: n.message,
        });
      }

      if (dismissedIdsRef.current.has(n.notification_id)) return;
      setNotifications((prev) =>
        prev.some((existing) => existing.notification_id === n.notification_id)
          ? prev
          : [n, ...prev]
      );
    }

    function connect() {
      if (cancelled) return;
      const accessToken = localStorage.getItem("access_token");
      if (!accessToken) {
        // Not logged in yet (or a logout raced this reconnect) — this
        // component only ever mounts behind the authenticated
        // dashboard layout, so this is expected to resolve itself
        // almost immediately rather than needing special handling.
        scheduleReconnect();
        return;
      }

      const es = new EventSource(getNotificationStreamUrl(accessToken));
      source = es;

      es.onopen = () => {
        attempt = 0;
      };

      es.addEventListener("notification", handleNotificationEvent as EventListener);

      es.onerror = () => {
        es.close();
        if (source === es) source = null;
        scheduleReconnect();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      source?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogout = () => {
    authService.logout();
    logout();
    router.push("/login");
  };

  const markAllRead = async () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    try {
      await markAllNotificationsRead();
    } catch {
      // ignore — the next SSE event or manual refresh reconciles either way
    }
  };

  const handleNotificationClick = async (notification: NotificationItem) => {
    if (!notification.is_read) {
      setNotifications((prev) =>
        prev.map((n) => (n.notification_id === notification.notification_id ? { ...n, is_read: true } : n))
      );
      try {
        await markNotificationRead(notification.notification_id);
      } catch {
        // ignore
      }
    }
    const href = resolveNotificationHref(notification.link);
    if (href) {
      router.push(href);
    }
  };

  const removeNotification = (notificationId: string) => {
    dismissedIdsRef.current.add(notificationId);
    setNotifications((prev) => prev.filter((n) => n.notification_id !== notificationId));
  };

  const clearAllNotifications = () => {
    notifications.forEach((n) => dismissedIdsRef.current.add(n.notification_id));
    setNotifications([]);
  };

  return (
    <header className="sticky top-0 z-30 hidden h-16 items-center justify-end border-b border-border bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:flex print:hidden">
      {/* Right Section */}
      <div className="flex items-center gap-2">
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
              <div className="flex items-center gap-3">
                {unreadCount > 0 && (
                  <button
                    onClick={markAllRead}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    {t("navbar.markAllRead")}
                  </button>
                )}
                {notifications.length > 0 && (
                  <button
                    onClick={clearAllNotifications}
                    className="text-xs font-medium text-muted-foreground hover:text-destructive hover:underline"
                  >
                    {t("navbar.clearAll")}
                  </button>
                )}
              </div>
            </div>
            <DropdownMenuSeparator />

            {notifications.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                {t("navbar.noNotifications")}
              </p>
            ) : (
              <div className="max-h-96 overflow-y-auto">
                <AnimatePresence initial={false}>
                  {notifications.map((notification) => (
                    <motion.div
                      key={notification.notification_id}
                      layout
                      initial={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0, marginTop: 0, marginBottom: 0 }}
                      transition={{ duration: 0.2, ease: "easeInOut" }}
                      className="overflow-hidden"
                    >
                      <DropdownMenuItem
                        className="relative flex-col items-start gap-0.5 py-2 pr-8"
                        onClick={() => handleNotificationClick(notification)}
                      >
                        <button
                          type="button"
                          aria-label="Remove notification"
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            removeNotification(notification.notification_id);
                          }}
                          className="absolute right-2 top-2 rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                        <div className="flex w-full items-center gap-2">
                          <span
                            className={cn(
                              "h-1.5 w-1.5 shrink-0 rounded-full",
                              notification.is_read ? "bg-transparent" : "bg-primary"
                            )}
                          />
                          <span className="text-sm font-medium">{notification.title}</span>
                        </div>
                        <p className="pl-3.5 text-xs text-muted-foreground">
                          {notification.message}
                        </p>
                        <p className="pl-3.5 text-[11px] text-muted-foreground/70">
                          {timeAgo(notification.created_at)}
                        </p>
                      </DropdownMenuItem>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
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
