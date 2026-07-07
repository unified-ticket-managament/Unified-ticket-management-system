import { useCallback, useEffect, useMemo, useState } from "react";
import { Paperclip, RefreshCw, Search, Ticket as TicketIcon } from "lucide-react";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { useApiAction } from "@tw/hooks/useApiAction";
import { useDebouncedValue } from "@tw/hooks/useDebouncedValue";
import { getInbox, openInboxThread } from "@tw/api/inbox";
import { listClients } from "@tw/api/clients";
import { useAuthContext } from "@tw/context/AuthContext";
import { useToast } from "@tw/context/ToastContext";
import { useWorkflowContext } from "@tw/context/WorkflowContext";
import type { ClientResponse, InboxItem, InboxView } from "@tw/types";

const SUPERVISOR_ROLES = ["Site Lead", "Super Admin"];

function initials(name: string) {
  return name.trim().charAt(0).toUpperCase() || "?";
}

// ==========================================================
// Tabs
//
//   - Pending / Replied / Ticketed: the three states a root email
//     can be in, always scoped to "my clients".
//   - All Inboxes: the Manager/Super Admin escape hatch — every
//     client's mail, not just this user's own. Rendered as its own
//     tab, not a filter, so it's unmistakably a different view.
// ==========================================================

type TabKey = InboxView;

const OWN_TABS: Array<{ key: TabKey; label: string }> = [
  { key: "pending", label: "Pending" },
  { key: "replied", label: "Replied" },
  { key: "ticketed", label: "Ticketed" },
];

// ==========================================================
// Time filter
// ==========================================================

type TimeFilterKey = "ALL" | "1H" | "TODAY" | "24H" | "1W";

const TIME_FILTERS: Array<{ key: TimeFilterKey; label: string }> = [
  { key: "ALL", label: "All Time" },
  { key: "1H", label: "Last 1 Hour" },
  { key: "TODAY", label: "Today" },
  { key: "24H", label: "Last 24 Hours" },
  { key: "1W", label: "Last 1 Week" },
];

function isWithinTimeFilter(receivedAt: string, filter: TimeFilterKey, now: Date): boolean {
  if (filter === "ALL") return true;

  const receivedTime = new Date(receivedAt).getTime();
  const nowTime = now.getTime();

  switch (filter) {
    case "1H":
      return nowTime - receivedTime <= 60 * 60 * 1000;
    case "24H":
      return nowTime - receivedTime <= 24 * 60 * 60 * 1000;
    case "1W":
      return nowTime - receivedTime <= 7 * 24 * 60 * 60 * 1000;
    case "TODAY": {
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      return receivedTime >= startOfToday;
    }
    default:
      return true;
  }
}

const SEARCHABLE_FIELDS: Array<(item: InboxItem) => string> = [
  (item) => item.client_name,
  (item) => item.subject,
  (item) => item.from_email ?? "",
];

function matchesSearch(item: InboxItem, term: string): boolean {
  if (!term) return true;
  return SEARCHABLE_FIELDS.some((getField) => getField(item).toLowerCase().includes(term));
}

const selectClass =
  "rounded-md2 border border-border bg-surface px-2.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

const STATUS_BADGE: Record<string, { tone: "warning" | "success" | "default"; label?: string }> = {
  PENDING: { tone: "warning" },
  ASSIGNED: { tone: "success", label: "REPLIED" },
};

export function AgentInbox() {
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const { currentUser } = useAuthContext();
  const { pushToast } = useToast();

  const isSupervisor = Boolean(currentUser && SUPERVISOR_ROLES.includes(currentUser.role));

  const [rowsByTab, setRowsByTab] = useState<Record<TabKey, InboxItem[]>>({
    pending: [],
    replied: [],
    ticketed: [],
    all: [],
  });
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("pending");
  const [clientFilter, setClientFilter] = useState<string>("ALL");
  const [timeFilter, setTimeFilter] = useState<TimeFilterKey>("ALL");
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());

  const { run: runOpen } = useApiAction(openInboxThread);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const clientId = clientFilter === "ALL" ? undefined : clientFilter;

      const [pending, replied, ticketed, clientList] = await Promise.all([
        getInbox("pending", { clientId }),
        getInbox("replied", { clientId }),
        getInbox("ticketed", { clientId }),
        listClients(),
      ]);

      const next: Record<TabKey, InboxItem[]> = {
        pending: pending.items,
        replied: replied.items,
        ticketed: ticketed.items,
        all: [],
      };

      if (isSupervisor) {
        const all = await getInbox("all", { clientId, scope: "all" });
        next.all = all.items;
      }

      setRowsByTab(next);
      setClients(clientList);
    } catch (error) {
      pushToast(
        error instanceof Error ? error.message : "Failed to load inbox.",
        "error"
      );
    } finally {
      setIsLoading(false);
    }
  }, [pushToast, clientFilter, isSupervisor]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleOpen(interactionId: string) {
    setOpeningId(interactionId);
    const result = await runOpen(interactionId);
    setOpeningId(null);

    if (result) {
      setSelectedEmail(result);
      setOpenedIds((prev) => {
        const next = new Set(prev);
        next.add(interactionId);
        return next;
      });
    }
  }

  function handleListKeyDown(e: React.KeyboardEvent<HTMLUListElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const buttons = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
    const currentIndex = buttons.findIndex((b) => b === document.activeElement);
    if (currentIndex === -1) return;
    e.preventDefault();
    const nextIndex =
      e.key === "ArrowDown"
        ? Math.min(currentIndex + 1, buttons.length - 1)
        : Math.max(currentIndex - 1, 0);
    buttons[nextIndex]?.focus();
  }

  const now = useMemo(() => new Date(), [rowsByTab, timeFilter]);
  const debouncedSearch = useDebouncedValue(search, 300);
  const term = debouncedSearch.trim().toLowerCase();

  const applyFilters = useCallback(
    (rows: InboxItem[]) =>
      rows.filter(
        (row) => isWithinTimeFilter(row.received_at, timeFilter, now) && matchesSearch(row, term)
      ),
    [timeFilter, now, term]
  );

  const tabRows: Record<TabKey, InboxItem[]> = {
    pending: applyFilters(rowsByTab.pending),
    replied: applyFilters(rowsByTab.replied),
    ticketed: applyFilters(rowsByTab.ticketed),
    all: applyFilters(rowsByTab.all),
  };

  const filteredItems = tabRows[activeTab];
  const managedClientCount = currentUser
    ? clients.filter((c) => c.account_manager_id === currentUser.user_id).length
    : 0;

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between border-b border-border px-4 py-4">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">
            Inbox — My Clients
          </h3>
          <p className="mt-0.5 text-[11px] text-muted">
            {rowsByTab.pending.length} pending action
            {managedClientCount > 0 ? ` · across ${managedClientCount} clients you manage` : ""}
          </p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          isLoading={isLoading}
          onClick={refresh}
          aria-label="Refresh inbox"
        >
          <RefreshCw size={14} />
        </Button>
      </div>

      <div className="flex items-center justify-between gap-1 border-b border-border px-3 py-2">
        <div className="flex items-center gap-1">
          {OWN_TABS.map((tab) => {
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                aria-pressed={isActive}
                className={`flex items-center gap-1.5 rounded-md2 px-2.5 py-1.5 text-[11.5px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                  isActive
                    ? "bg-accent/10 text-accent"
                    : "text-muted hover:bg-surfaceHover hover:text-slate-700"
                }`}
              >
                {tab.label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                    isActive ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {tabRows[tab.key].length}
                </span>
              </button>
            );
          })}
        </div>
        {isSupervisor && (
          <button
            onClick={() => setActiveTab("all")}
            aria-pressed={activeTab === "all"}
            title="Every client's mail, not just yours — for when an Account Manager is on leave"
            className={`flex items-center gap-1.5 rounded-md2 px-2.5 py-1.5 text-[11.5px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
              activeTab === "all"
                ? "bg-accent/10 text-accent"
                : "text-muted hover:bg-surfaceHover hover:text-slate-700"
            }`}
          >
            All Inboxes
            <span
              className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                activeTab === "all" ? "bg-accent/20 text-accent" : "bg-slate-100 text-slate-500"
              }`}
            >
              {tabRows.all.length}
            </span>
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2 border-b border-border px-3 py-2.5">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sender or subject..."
            aria-label="Search inbox by sender or subject"
            className="w-full rounded-md2 border border-border bg-canvas py-2 pl-8 pr-3 text-xs text-slate-900 placeholder:text-muted/70 focus:border-accent focus:bg-surface focus:outline-none"
          />
        </div>
        <div className="flex gap-2">
          <select
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
            aria-label="Filter by client"
            className={`${selectClass} flex-1`}
          >
            <option value="ALL">All clients</option>
            {clients.map((client) => (
              <option key={client.client_id} value={client.client_id}>
                {client.name}
              </option>
            ))}
          </select>
          <select
            value={timeFilter}
            onChange={(e) => setTimeFilter(e.target.value as TimeFilterKey)}
            aria-label="Filter by time received"
            className={selectClass}
          >
            {TIME_FILTERS.map((tf) => (
              <option key={tf.key} value={tf.key}>
                {tf.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {isLoading && filteredItems.length === 0 ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : filteredItems.length === 0 ? (
          <EmptyState
            icon="📭"
            title={
              activeTab === "pending"
                ? "Nothing pending"
                : activeTab === "replied"
                ? "Nothing replied yet"
                : activeTab === "ticketed"
                ? "Nothing ticketed yet"
                : "No mail yet"
            }
            description={
              activeTab === "pending"
                ? "Create a dummy email addressed to one of your clients, then refresh to see it appear here."
                : "Mail will move here once it's been actioned."
            }
          />
        ) : (
          <ul className="divide-y divide-border" onKeyDown={handleListKeyDown}>
            {filteredItems.map((item) => {
              const isSelected = selectedEmail?.interaction_id === item.interaction_id;
              const isUnread = item.status === "PENDING" && !openedIds.has(item.interaction_id);
              const badge = STATUS_BADGE[item.status] ?? { tone: "default" as const };
              return (
                <li key={item.interaction_id}>
                  <button
                    onClick={() => handleOpen(item.interaction_id)}
                    disabled={openingId === item.interaction_id}
                    aria-label={`${isUnread ? "Unread. " : ""}Email from ${item.client_name}: ${item.subject}`}
                    aria-current={isSelected}
                    className={`flex w-full items-start gap-3 border-l-2 px-4 py-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40 ${
                      isSelected
                        ? "border-l-accent bg-accent/5"
                        : "border-l-transparent hover:bg-surfaceHover"
                    }`}
                  >
                    <div className="relative flex-none">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10 text-xs font-semibold text-accent">
                        {initials(item.client_name)}
                      </div>
                      {isUnread && (
                        <span
                          className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent"
                          aria-hidden="true"
                        />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p
                          className={`truncate text-[13px] ${
                            isUnread ? "font-bold text-slate-900" : "font-medium text-slate-700"
                          }`}
                        >
                          {item.client_name}
                        </p>
                        <span className="flex-none text-[10px] font-medium text-muted">
                          {new Date(item.received_at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                      {(item.from_email || item.to_email) && (
                        <p className="truncate text-[10.5px] text-muted">
                          {item.from_email ?? "unknown sender"}
                          {item.to_email ? ` → ${item.to_email}` : ""}
                        </p>
                      )}
                      <p
                        className={`mt-0.5 truncate text-xs ${
                          isUnread ? "text-slate-700" : "text-slate-500"
                        }`}
                      >
                        {item.subject}
                      </p>
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <Badge tone={badge.tone} dot>
                          {badge.label ?? item.status}
                        </Badge>
                        {item.ticket_id && (
                          <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
                            <TicketIcon size={11} className="flex-none" />
                            Ticketed
                          </span>
                        )}
                        {item.has_attachments && (
                          <span className="flex items-center gap-0.5 text-[10px] text-muted">
                            <Paperclip size={11} />
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
