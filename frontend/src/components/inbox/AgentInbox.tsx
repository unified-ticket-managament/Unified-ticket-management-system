import { useCallback, useEffect, useMemo, useState } from "react";
import { Paperclip, RefreshCw, Search } from "lucide-react";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { EmptyState } from "@/components/common/EmptyState";
import { SkeletonRows } from "@/components/common/Skeleton";
import { useApiAction } from "@/hooks/useApiAction";
import { getAgentInbox, openEmail } from "@/api/agent";
import { useWorkflowContext } from "@/context/WorkflowContext";
import type { InboxItem } from "@/types";

function initials(name: string) {
  return name.trim().charAt(0).toUpperCase() || "?";
}

export function AgentInbox() {
  const { agentName, selectedEmail, setSelectedEmail } = useWorkflowContext();
  const [items, setItems] = useState<InboxItem[]>([]);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Session-local read tracking — this app has no backend read-status
  // field, so "unread" simply means "not yet opened by this agent in
  // this session," derived from real clicks rather than fabricated data.
  const [openedIds, setOpenedIds] = useState<Set<string>>(new Set());

  const { run: runFetch, isLoading: isFetching } = useApiAction(getAgentInbox);
  const { run: runOpen } = useApiAction(openEmail);

  const refresh = useCallback(async () => {
    const result = await runFetch(agentName);
    if (result) setItems(result.items);
  }, [agentName, runFetch]);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentName]);

  async function handleOpen(interactionId: string) {
    setOpeningId(interactionId);
    const result = await runOpen(agentName, interactionId);
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

  const filteredItems = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return items;
    return items.filter(
      (item) =>
        item.client_name.toLowerCase().includes(term) ||
        item.subject.toLowerCase().includes(term)
    );
  }, [items, search]);

  return (
    <div className="flex h-full flex-col rounded-md2 border border-border bg-surface shadow-xs">
      <div className="flex items-center justify-between border-b border-border px-4 py-4">
        <div>
          <h3 className="text-[13px] font-semibold text-slate-900">
            Interactions List
          </h3>
          <p className="mt-0.5 text-[11px] text-muted">{items.length} pending</p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          isLoading={isFetching}
          onClick={refresh}
          aria-label="Refresh inbox"
        >
          <RefreshCw size={14} />
        </Button>
      </div>

      <div className="border-b border-border px-3 py-2.5">
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sender or subject..."
            aria-label="Search inbox by sender or subject"
            className="w-full rounded-md2 border border-border bg-canvas py-2 pl-8 pr-3 text-xs text-slate-900 placeholder:text-muted/70 focus:border-accent focus:bg-white focus:outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {isFetching && items.length === 0 ? (
          <div className="p-4">
            <SkeletonRows rows={5} />
          </div>
        ) : filteredItems.length === 0 ? (
          <EmptyState
            icon="📭"
            title={items.length === 0 ? "Inbox is empty" : "No matches"}
            description={
              items.length === 0
                ? "Create a dummy email, then refresh to see it appear here, unassigned and waiting."
                : "Try a different search term."
            }
          />
        ) : (
          <ul className="divide-y divide-border" onKeyDown={handleListKeyDown}>
            {filteredItems.map((item) => {
              const isSelected =
                selectedEmail?.interaction_id === item.interaction_id;
              const isUnread = !openedIds.has(item.interaction_id);
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
                        <Badge tone="warning" dot>
                          {item.status}
                        </Badge>
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
