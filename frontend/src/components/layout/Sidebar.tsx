import { NavLink } from "react-router-dom";
import {
  ChevronsUpDown,
  Inbox,
  LayoutDashboard,
  LogOut,
  MailPlus,
  MessageSquare,
  ShieldCheck,
  Ticket,
  X,
} from "lucide-react";
import { useWorkflowContext } from "@/context/WorkflowContext";
import { useToast } from "@/context/ToastContext";
import { DEFAULT_AGENT } from "@/lib/agents";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/create-mail", label: "Create Dummy Mail", icon: MailPlus },
  { to: "/inbox", label: "Inbox", icon: Inbox },
  { to: "/interactions", label: "Interactions", icon: MessageSquare },
  { to: "/tickets", label: "Tickets", icon: Ticket },
  { to: "/audit-logs", label: "Audit Log", icon: ShieldCheck },
];

function initials(name: string) {
  return name
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

interface SidebarProps {
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({ mobileOpen, onCloseMobile }: SidebarProps) {
  const { agentName, setAgentName, agents, setSelectedEmail, setActiveTicket, setTimeline } =
    useWorkflowContext();
  const { pushToast } = useToast();

  function handleLogout() {
    const resetAgent = agents[0]?.name ?? DEFAULT_AGENT;
    setSelectedEmail(null);
    setActiveTicket(null);
    setTimeline([]);
    setAgentName(resetAgent);
    pushToast("Session cleared. Acting as " + resetAgent + ".", "info");
    onCloseMobile();
  }

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-screen w-64 flex-none flex-col border-r border-border bg-surface transition-transform duration-200 ease-in-out lg:static lg:z-auto lg:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between gap-2.5 border-b border-border px-5 py-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 bg-accent text-sm font-bold text-white shadow-xs">
              T
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold leading-none text-slate-900">
                ProbePS
              </p>
              <p className="mt-1 truncate text-[11px] leading-none text-muted">
                Support Desk
              </p>
            </div>
          </div>
          <button
            onClick={onCloseMobile}
            aria-label="Close navigation menu"
            className="flex h-9 w-9 flex-none items-center justify-center rounded-md2 text-muted transition-colors hover:bg-surfaceHover hover:text-slate-900 lg:hidden"
          >
            <X size={18} />
          </button>
        </div>

        <nav
          aria-label="Primary"
          className="flex flex-1 flex-col gap-0.5 overflow-y-auto scrollbar-thin px-3 py-4"
        >
          <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            Workspace
          </p>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={onCloseMobile}
                className={({ isActive }) =>
                  `group relative flex items-center gap-2.5 rounded-md2 px-3 py-2.5 text-[13px] font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                    isActive
                      ? "bg-accent-50 text-accent"
                      : "text-slate-600 hover:bg-surfaceHover hover:text-slate-900"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={`absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-accent transition-opacity ${
                        isActive ? "opacity-100" : "opacity-0"
                      }`}
                    />
                    <Icon size={17} strokeWidth={2.1} className="flex-none" />
                    <span className="truncate">{item.label}</span>
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        <div className="border-t border-border p-3">
          <div className="group relative flex items-center gap-2.5 rounded-md2 px-2.5 py-2.5 transition-colors hover:bg-surfaceHover">
            <div className="relative flex-none">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                {initials(agentName)}
              </div>
              <span
                className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-success"
                title="Active"
              />
            </div>
            <div className="min-w-0 flex-1">
              <select
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                className="w-full cursor-pointer truncate bg-transparent text-[13px] font-semibold text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                aria-label="Acting as agent"
              >
                {agents.length > 0 ? (
                  agents.map((agent) => (
                    <option key={agent.user_id} value={agent.name}>
                      {agent.name}
                    </option>
                  ))
                ) : (
                  <option value={agentName}>{agentName}</option>
                )}
              </select>
              <p className="text-[11px] leading-none text-muted">Agent · Active</p>
            </div>
            <ChevronsUpDown size={13} className="flex-none text-muted" />
          </div>

          <button
            onClick={handleLogout}
            className="mt-1 flex min-h-[40px] w-full items-center gap-2.5 rounded-md2 px-3 py-2 text-[13px] font-medium text-muted transition-colors hover:bg-danger/5 hover:text-danger focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-danger/30"
          >
            <LogOut size={16} strokeWidth={2.1} />
            Log out
          </button>
        </div>
      </aside>
    </>
  );
}
