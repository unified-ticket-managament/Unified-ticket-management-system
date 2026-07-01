import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, Menu, Search } from "lucide-react";
import { useApiAction } from "@/hooks/useApiAction";
import { getTicket } from "@/api/ticket";
import { useWorkflowContext } from "@/context/WorkflowContext";

interface TopbarProps {
  title: string;
  description?: string;
  onOpenMenu: () => void;
}

function initials(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function Topbar({ title, description, onOpenMenu }: TopbarProps) {
  const navigate = useNavigate();
  const { agentName } = useWorkflowContext();
  const [ticketId, setTicketId] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);
  const { run: runGetTicket, isLoading } = useApiAction(getTicket);

  async function handleJump(e: React.FormEvent) {
    e.preventDefault();
    if (!ticketId.trim()) return;
    const ticket = await runGetTicket(ticketId.trim(), agentName);
    if (ticket) {
      setTicketId("");
      navigate(`/tickets/${ticket.ticket_id}`);
    }
  }

  return (
    <header className="flex items-center justify-between gap-3 border-b border-border bg-white px-4 py-4 sm:gap-6 sm:px-7">
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
            className="w-full rounded-md2 border border-border bg-canvas py-2.5 pl-10 pr-3 text-[13px] text-slate-900 shadow-xs transition-all placeholder:text-muted/70 focus:border-accent focus:bg-white focus:outline-none focus:ring-4 focus:ring-accent/10"
          />
        </form>

        <div className="relative">
          <button
            onClick={() => setShowNotifications((v) => !v)}
            className="flex h-10 w-10 items-center justify-center rounded-md2 border border-border bg-white text-muted transition-colors hover:bg-surfaceHover hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label="Notifications"
            aria-haspopup="true"
            aria-expanded={showNotifications}
          >
            <Bell size={16} />
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
                className="absolute right-0 z-50 mt-2 w-64 rounded-md2 border border-border bg-white p-4 text-center shadow-popover animate-popIn"
              >
                <p className="text-xs font-medium text-slate-700">You're all caught up</p>
                <p className="mt-1 text-[11px] text-muted">No new notifications right now.</p>
              </div>
            </>
          )}
        </div>

        <div className="hidden items-center gap-2.5 rounded-md2 border border-border bg-white py-1.5 pl-1.5 pr-3 sm:flex">
          <div className="relative flex-none">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/10 text-[11px] font-semibold text-accent">
              {initials(agentName)}
            </div>
            <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border-2 border-white bg-success" />
          </div>
          <span className="max-w-[9rem] truncate text-[13px] font-medium text-slate-700">
            {agentName}
          </span>
        </div>
      </div>
    </header>
  );
}
