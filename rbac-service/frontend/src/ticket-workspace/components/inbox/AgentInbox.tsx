import { MessageSquare, Paperclip, RefreshCw, Search, Ticket as TicketIcon } from "lucide-react";
import { Avatar } from "@tw/components/common/Avatar";
import { Badge } from "@tw/components/common/Badge";
import { Button } from "@tw/components/common/Button";
import { EmptyState } from "@tw/components/common/EmptyState";
import { SkeletonRows } from "@tw/components/common/Skeleton";
import { TIME_FILTERS, type useMailInbox } from "@tw/hooks/useMailInbox";

type AgentInboxProps = ReturnType<typeof useMailInbox>;

const selectClass =
  "rounded-md2 border border-border bg-surface px-2.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

const STATUS_BADGE: Record<string, { tone: "warning" | "success" | "default"; label?: string }> = {
  PENDING: { tone: "warning" },
  ASSIGNED: { tone: "success", label: "REPLIED" },
};

const EMPTY_STATE_COPY: Record<string, { title: string; description: string }> = {
  pending: {
    title: "Nothing pending",
    description: "Create a dummy email addressed to one of your clients, then refresh to see it appear here.",
  },
  unassigned: { title: "Nothing unassigned", description: "Every pending item has already been claimed." },
  mine: { title: "You haven't claimed anything", description: "Claimed items you're working show up here." },
  sent: { title: "Nothing sent yet", description: "Replies you send show up here." },
  drafts: { title: "No drafts", description: "Reply text you save without sending shows up here." },
  replied: { title: "Nothing replied yet", description: "Mail will move here once it's been actioned." },
  ticketed: { title: "Nothing ticketed yet", description: "Mail will move here once it's been actioned." },
  archived: { title: "Nothing archived", description: "Mail will move here once it's been actioned." },
  all: { title: "No mail yet", description: "Mail will move here once it's been actioned." },
};

export function AgentInbox({
  isSupervisor,
  isLoading,
  openingId,
  openedIds,
  clients,
  clientFilter,
  setClientFilter,
  timeFilter,
  setTimeFilter,
  search,
  setSearch,
  activeView,
  filteredItems,
  managedClientCount,
  refresh,
  openThread,
  selectedEmail,
}: AgentInboxProps) {

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

  const emptyCopy = EMPTY_STATE_COPY[activeView] ?? EMPTY_STATE_COPY.all;

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between border-b border-border px-4 py-4">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">
            {isSupervisor && activeView === "all" ? "All Inboxes" : "My Clients"}
          </h3>
          <p className="mt-0.5 text-[11px] text-muted">
            {filteredItems.length} item{filteredItems.length === 1 ? "" : "s"}
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
            onChange={(e) => setTimeFilter(e.target.value as typeof timeFilter)}
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
          <EmptyState icon="📭" title={emptyCopy.title} description={emptyCopy.description} />
        ) : (
          <ul className="divide-y divide-border" onKeyDown={handleListKeyDown}>
            {filteredItems.map((item) => {
              const isSelected = selectedEmail?.interaction_id === item.interaction_id;
              const isUnread = item.status === "PENDING" && !openedIds.has(item.interaction_id);
              const badge = STATUS_BADGE[item.status] ?? { tone: "default" as const };
              return (
                <li key={item.interaction_id}>
                  <button
                    onClick={() => openThread(item.interaction_id)}
                    disabled={openingId === item.interaction_id}
                    aria-label={`${isUnread ? "Unread. " : ""}Email from ${item.client_name}: ${item.subject}`}
                    aria-current={isSelected}
                    className={`flex w-full items-start gap-3 border-l-2 px-4 py-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/40 ${
                      isSelected
                        ? "border-l-accent bg-accent/5"
                        : "border-l-transparent hover:bg-surfaceHover"
                    }`}
                  >
                    <Avatar
                      name={item.client_name}
                      indicator={isUnread ? "warning" : undefined}
                    />
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
                          {new Date(item.latest_at ?? item.received_at).toLocaleTimeString([], {
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
                      {item.reply_count > 0 && item.latest_message && (
                        // Outlook-style "latest message" preview — the
                        // most recent reply in the thread, not the
                        // root email's own body, so this row reflects
                        // whatever anyone (agent or client) last said.
                        <p className="mt-0.5 truncate text-[10.5px] text-muted">
                          <span className="font-medium text-slate-600">
                            {item.latest_sender ?? "Reply"}:
                          </span>{" "}
                          {item.latest_message}
                        </p>
                      )}
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
                        {item.reply_count > 0 && (
                          <span className="flex items-center gap-1 text-[10px] font-medium text-muted">
                            <MessageSquare size={11} className="flex-none" />
                            {item.reply_count}
                          </span>
                        )}
                        {item.has_attachments && (
                          <span className="flex items-center gap-0.5 text-[10px] text-muted">
                            <Paperclip size={11} />
                          </span>
                        )}
                        {item.claimed_by_name && !item.ticket_id && (
                          <span className="text-[10px] font-medium text-muted">
                            · {item.claimed_by_name}
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
