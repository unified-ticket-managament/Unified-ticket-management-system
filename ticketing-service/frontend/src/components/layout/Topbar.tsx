import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Menu, Moon, Search, Sun } from "lucide-react";
import { Avatar } from "@/components/common/Avatar";
import { useApiAction } from "@/hooks/useApiAction";
import {
  getNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "@/api/notifications";
import { getTicket } from "@/api/ticket";
import { useAuthContext } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { useToast } from "@/context/ToastContext";
import { formatDateTime } from "@/lib/format";
import { isValidUUID } from "@/lib/validation";

const NOTIFICATION_POLL_INTERVAL_MS = 30_000;
const NOTIFICATION_PREVIEW_COUNT = 5;

interface TopbarProps {
  title: string;
  description?: string;
  onOpenMenu: () => void;
}

export function Topbar({ title, description, onOpenMenu }: TopbarProps) {
  const navigate = useNavigate();
  const { currentUser } = useAuthContext();
  const { theme, toggleTheme } = useTheme();
  const { pushToast } = useToast();
  const [ticketId, setTicketId] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const { run: runGetTicket, isLoading } = useApiAction(getTicket);

  // Polls the real notification feed so the bell reflects new mail,
  // ticket assignments, permission/edit-access decisions, etc. without
  // a full-page refresh. Silent on poll failures — the badge just
  // keeps showing the last good count rather than flashing an error
  // toast on every tick, same rationale as TicketAuditLog.
  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await getNotifications();
        if (!cancelled) {
          setNotifications(data.items);
          setUnreadCount(data.unread_count);
        }
      } catch {
        // ignore
      }
    }

    load();
    const interval = window.setInterval(load, NOTIFICATION_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  async function handleNotificationClick(notification: NotificationItem) {
    if (!notification.is_read) {
      setNotifications((prev) =>
        prev.map((n) =>
          n.notification_id === notification.notification_id ? { ...n, is_read: true } : n
        )
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
      try {
        await markNotificationRead(notification.notification_id);
      } catch {
        // ignore
      }
    }
    setShowNotifications(false);
    if (notification.link) {
      navigate(notification.link);
    }
  }

  async function handleMarkAllRead() {
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch {
      // ignore — next poll tick reconciles either way
    }
  }

  async function handleJump(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = ticketId.trim();
    if (!trimmed) return;
    if (!isValidUUID(trimmed)) {
      pushToast("Please enter a valid ticket ID.", "error");
      return;
    }
    const ticket = await runGetTicket(trimmed);
    if (ticket) {
      setTicketId("");
      navigate(`/tickets/${ticket.ticket_id}`);
    }
  }

  return (
    <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-4 sm:gap-6 sm:px-7">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={onOpenMenu}
          aria-label="Open navigation menu"
          className="flex h-10 w-10 flex-none items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 lg:hidden"
        >
          <Menu size={19} />
        </button>
        <div className="min-w-0">
          <p className="mb-1 hidden text-[11px] font-medium text-muted sm:block">
            Workspace <span className="mx-1 text-slate-300">/</span>
            <span className="text-slate-500">{title}</span>
          </p>
          <h1 className="truncate text-[16px] font-semibold leading-tight text-slate-900 sm:text-[17px]">
            {title}
          </h1>
          {description && (
            <p className="mt-0.5 hidden truncate text-xs text-muted sm:block">{description}</p>
          )}
        </div>
      </div>

      <div className="flex flex-none items-center gap-2 sm:gap-3">
        <form onSubmit={handleJump} className="relative hidden w-56 md:block lg:w-72">
          <Search
            size={15}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            value={ticketId}
            onChange={(e) => setTicketId(e.target.value)}
            placeholder="Search a ticket by ID..."
            disabled={isLoading}
            aria-label="Search a ticket by ID"
            className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-[13px] text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
        </form>

        <button
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          className="flex h-10 w-10 flex-none items-center justify-center rounded-md2 border border-border bg-surface text-muted transition-colors hover:bg-surfaceHover hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        <div className="relative">
          <button
            onClick={() => setShowNotifications((v) => !v)}
            className="relative flex h-10 w-10 items-center justify-center rounded-md2 border border-border bg-surface text-muted transition-colors hover:bg-surfaceHover hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ""}`}
            aria-haspopup="true"
            aria-expanded={showNotifications}
          >
            <Bell size={16} />
            {unreadCount > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full border-2 border-surface bg-danger px-1 text-[9px] font-bold leading-none text-white">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
          </button>
          {showNotifications && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowNotifications(false)}
              />
              <div
                role="dialog"
                aria-label="Notifications"
                className="absolute right-0 z-50 mt-2 w-80 rounded-md2 border border-border bg-surface shadow-popover animate-popIn"
              >
                {notifications.length === 0 ? (
                  <div className="p-4 text-center">
                    <p className="text-xs font-medium text-slate-700">You're all caught up</p>
                    <p className="mt-1 text-[11px] text-muted">No new notifications right now.</p>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
                      <p className="text-xs font-semibold text-slate-900">Notifications</p>
                      {unreadCount > 0 && (
                        <button
                          onClick={handleMarkAllRead}
                          className="text-[11px] font-semibold text-accent transition-colors hover:text-accent-700"
                        >
                          Mark all read
                        </button>
                      )}
                    </div>
                    <ul className="max-h-80 divide-y divide-border overflow-y-auto">
                      {notifications.slice(0, NOTIFICATION_PREVIEW_COUNT).map((item) => (
                        <li key={item.notification_id}>
                          <button
                            onClick={() => handleNotificationClick(item)}
                            className="flex w-full items-start gap-2.5 px-4 py-3 text-left transition-colors hover:bg-surfaceHover"
                          >
                            <span
                              className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${
                                item.is_read ? "bg-transparent" : "bg-accent"
                              }`}
                            />
                            <div className="min-w-0">
                              <p className="truncate text-xs font-semibold text-slate-900">
                                {item.title}
                              </p>
                              <p className="truncate text-[11px] text-muted">{item.message}</p>
                              <p className="mt-0.5 text-[10px] text-muted/80">
                                {formatDateTime(item.created_at)}
                              </p>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </>
          )}
        </div>

        <div className="hidden items-center gap-2.5 rounded-md2 border border-border bg-surface py-1.5 pl-1.5 pr-3 sm:flex">
          <Avatar name={currentUser?.name ?? ""} size="sm" indicator="success" />
          <span className="max-w-[9rem] truncate text-[13px] font-medium text-slate-700">
            {currentUser?.name}
          </span>
        </div>
      </div>
    </header>
  );
}
