import { useCallback, useEffect, useMemo, useState } from "react";
import { Paperclip, RefreshCw, Search, Ticket as TicketIcon } from "lucide-react";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { useApiAction } from "@/hooks/useApiAction";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { getAgentInbox, openEmail } from "@/api/agent";
import { listTickets } from "@/api/ticket";
import { getTicketTimeline } from "@/api/interaction";
import { useToast } from "@/context/ToastContext";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { InboxItem, InteractionStatus } from "@/types";

function initials(name: string) {
  return name.trim().charAt(0).toUpperCase() || "?";
}

// ==========================================================
// Unified row shape
//
// Pending-action rows come straight from the inbox endpoint.
// Processed rows are EMAIL interactions that already made it
// onto a ticket timeline (fetched via the same endpoints the
// Interactions page already uses) — reshaped to the same shape
// so the existing list rendering doesn't need to branch on source.
// ==========================================================

interface InboxRow {
  interaction_id: string;
  client_name: string;
  subject: string;
  message_id: string | null;
  received_at: string;
  status: InteractionStatus;
  has_attachments: boolean;
  ticketId: string | null;
  ticketTitle: string | null;
}

function fromPendingItem(item: InboxItem): InboxRow {
  return {
    interaction_id: item.interaction_id,
    client_name: item.client_name,
    subject: item.subject,
    message_id: item.message_id,
    received_at: item.received_at,
    status: item.status,
    has_attachments: item.has_attachments,
    ticketId: null,
    ticketTitle: null,
  };
}

// ==========================================================
// Tabs — mirror the actual inbox workflow rather than a
// generic read/unread or ownership split:
//   - Assigned: this agent's whole communication queue
//   - Pending Action: still needs a Create/Attach decision
//   - Processed: already turned into (or attached to) a ticket
// ==========================================================

type TabKey = "assigned" | "pendingAction" | "processed";

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "assigned", label: "Assigned" },
  { key: "pendingAction", label: "Pending Action" },
  { key: "processed", label: "Processed" },
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

// ==========================================================
// Search
//
// Structured as a list of field accessors so future fields
// (client, ticket category) can be added without touching the
// matching logic itself.
// ==========================================================

const SEARCHABLE_FIELDS: Array<(item: InboxRow) => string> = [
  (item) => item.client_name,
  (item) => item.subject,
];

function matchesSearch(item: InboxRow, term: string): boolean {
  if (!term) return true;
  return SEARCHABLE_FIELDS.some((getField) => getField(item).toLowerCase().includes(term));
}

const selectClass =
  "rounded-md2 border border-border bg-surface px-2.5 py-2 text-xs font-medium text-slate-700 shadow-xs transition-colors focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

export function AgentInbox() {
  const { selectedEmail, setSelectedEmail } = useWorkflowContext();
  const { pushToast } = useToast();

  const [pendingItems, setPendingItems] = useState<InboxItem[]>([]);
  const [processedRows, setProcessedRows] = useState<InboxRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("assigned");
  const [timeFilter, setTimeFilter] = useState<TimeFilterKey>("ALL");
  // Session-local read tracking — purely a visual "seen it" cue on
  // Pending Action rows now, not a tab filter (the tabs below are
  // driven by real ticket-linkage state instead).
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());

  const { run: runOpen } = useApiAction(openEmail);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const inbox = await getAgentInbox();
      setPendingItems(inbox.items);

      // Same aggregation the Interactions page already does: this
      // agent's tickets (plus unassigned ones), timeline per ticket,
      // keep only the EMAIL interactions — those are the ones that
      // started life as an inbox item and have since been processed.
      const tickets = await listTickets();
      const processed = (
        await Promise.all(
          tickets.map(async (ticket) => {
            const timeline = await getTicketTimeline(ticket.ticket_id);
            return timeline
              .filter((interaction) => interaction.interaction_type === "EMAIL")
              .map<InboxRow>((interaction) => ({
                interaction_id: interaction.interaction_id,
                client_name:
                  ticket.client_name ?? (interaction.payload.client_name as string) ?? "Unknown",
                subject: (interaction.payload.subject as string) ?? ticket.title,
                message_id: interaction.message_id,
                received_at: interaction.created_at,
                status: interaction.status,
                has_attachments: false,
                ticketId: ticket.ticket_id,
                ticketTitle: ticket.title,
              }));
          })
        )
      ).flat();
      setProcessedRows(processed);
    } catch (error) {
      pushToast(
        error instanceof Error ? error.message : "Failed to load inbox.",
        "error"
      );
    } finally {
      setIsLoading(false);
    }
  }, [pushToast]);

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

  const now = useMemo(() => new Date(), [pendingItems, processedRows, timeFilter]);
  const debouncedSearch = useDebouncedValue(search, 300);
  const term = debouncedSearch.trim().toLowerCase();

  const pendingRows = useMemo(() => pendingItems.map(fromPendingItem), [pendingItems]);

  const applyFilters = useCallback(
    (rows: InboxRow[]) =>
      rows
        .filter(
          (row) => isWithinTimeFilter(row.received_at, timeFilter, now) && matchesSearch(row, term)
        )
        .sort((a, b) => new Date(b.received_at).getTime() - new Date(a.received_at).getTime()),
    [timeFilter, now, term]
  );

  const pendingActionFiltered = useMemo(() => applyFilters(pendingRows), [applyFilters, pendingRows]);
  const processedFiltered = useMemo(() => applyFilters(processedRows), [applyFilters, processedRows]);
  const assignedFiltered = useMemo(
    () => applyFilters([...pendingRows, ...processedRows]),
    [applyFilters, pendingRows, processedRows]
  );

  const tabRows: Record<TabKey, InboxRow[]> = {
    assigned: assignedFiltered,
    pendingAction: pendingActionFiltered,
    processed: processedFiltered,
  };

  const filteredItems = tabRows[activeTab];
  const totalAssigned = pendingRows.length + processedRows.length;

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between border-b border-border px-4 py-4">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">
            Interactions List
          </h3>
          <p className="mt-0.5 text-[11px] text-muted">
            {pendingRows.length} pending action &middot; {totalAssigned} assigned
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

      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        {TABS.map((tab) => {
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

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {isLoading && pendingRows.length === 0 && processedRows.length === 0 ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : filteredItems.length === 0 ? (
          <EmptyState
            icon="📭"
            title={
              totalAssigned === 0
                ? "Nothing assigned yet"
                : activeTab === "pendingAction"
                ? "No emails need action"
                : activeTab === "processed"
                ? "Nothing processed yet"
                : "No matches"
            }
            description={
              totalAssigned === 0
                ? "Create a dummy email, then refresh to see it appear here."
                : activeTab === "pendingAction"
                ? "Every assigned email has already been turned into or attached to a ticket."
                : activeTab === "processed"
                ? "Once an email is turned into or attached to a ticket, it will show up here."
                : "Try a different search term or time range."
            }
          />
        ) : (
          <ul className="divide-y divide-border" onKeyDown={handleListKeyDown}>
            {filteredItems.map((item) => {
              const isSelected =
                selectedEmail?.interaction_id === item.interaction_id;
              const isUnread = !item.ticketId && !openedIds.has(item.interaction_id);
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
                      <p
                        className={`mt-0.5 truncate text-xs ${
                          isUnread ? "text-slate-700" : "text-slate-500"
                        }`}
                      >
                        {item.subject}
                      </p>
                      <div className="mt-1.5 flex items-center gap-1.5">
                        {item.ticketId ? (
                          <span className="flex items-center gap-1 truncate text-[10px] font-medium text-muted">
                            <TicketIcon size={11} className="flex-none" />
                            <span className="truncate">{item.ticketTitle}</span>
                          </span>
                        ) : (
                          <Badge tone="warning" dot>
                            {item.status}
                          </Badge>
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
