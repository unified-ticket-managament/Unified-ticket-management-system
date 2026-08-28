import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { Users, X } from "lucide-react";

import { listActiveDistributionLists } from "@tw/api/distributionLists";
import type { DistributionListRecipientCandidate } from "@tw/api/distributionLists";

// Shared, self-fetching Distribution List picker reused by every
// recipient-picking surface in the app (Mail Reply, Mail Forward,
// Mail Compose, Ticket Reply, Internal Note) and by the Rules
// forward_to action (via the shell-level ActionRow.tsx, which imports
// this same component/endpoint rather than a bespoke fetch). Always
// rendered as its own, additional field alongside whatever To/Cc/Bcc
// control a surface already has — a Distribution List is never
// folded into an existing email/user picker's own option list, since
// it expands to N members at send time, not one value. Fetches only
// active lists (GET /distribution-lists/active — authenticated-agent-
// only, deliberately not gated by rule:manage/rule:view_all).
export function DistributionListMultiSelect({
  label,
  hint,
  selectedIds,
  onChange,
}: {
  label: string;
  hint?: string;
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [lists, setLists] = useState<DistributionListRecipientCandidate[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listActiveDistributionLists(controller.signal)
      .then((data) => {
        setLists(data);
        setLoadError(false);
      })
      .catch(() => setLoadError(true))
      .finally(() => setIsLoading(false));
    return () => controller.abort();
  }, []);

  const selected = useMemo(
    () =>
      selectedIds
        .map((id) => lists.find((l) => l.distribution_list_id === id))
        .filter(Boolean) as DistributionListRecipientCandidate[],
    [lists, selectedIds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lists.filter((l) => {
      if (selectedIds.includes(l.distribution_list_id)) return false;
      if (!q) return true;
      return l.name.toLowerCase().includes(q) || (l.description ?? "").toLowerCase().includes(q);
    });
  }, [lists, query, selectedIds]);

  function add(id: string) {
    onChange([...selectedIds, id]);
    setQuery("");
  }

  function remove(id: string) {
    onChange(selectedIds.filter((existing) => existing !== id));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && selected.length > 0) {
      remove(selected[selected.length - 1].distribution_list_id);
    }
  }

  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate-600">{label}</span>
      <div className="relative">
        <div className="flex flex-wrap items-center gap-1.5 rounded-md2 border border-border bg-surface px-3.5 py-2 text-sm shadow-xs transition-all duration-150 focus-within:border-accent focus-within:outline-none focus-within:ring-4 focus-within:ring-accent/10 cursor-text">
          {selected.map((list) => (
            <span
              key={list.distribution_list_id}
              className="inline-flex items-center gap-1 rounded-full border border-teal/20 bg-teal/10 px-2 py-0.5 text-[11px] font-semibold text-teal"
            >
              <Users size={10} />
              {list.name} · {list.member_count}
              <button
                type="button"
                onClick={() => remove(list.distribution_list_id)}
                aria-label={`Remove ${list.name}`}
                className="rounded-full p-0.5 hover:bg-teal/20"
              >
                <X size={10} />
              </button>
            </span>
          ))}
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setIsOpen(true)}
            onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
            onKeyDown={handleKeyDown}
            placeholder={selected.length === 0 ? "Search distribution groups…" : ""}
            className="min-w-[140px] flex-1 border-none bg-transparent p-0 py-0.5 text-sm text-slate-900 placeholder:text-muted/60 focus:outline-none focus:ring-0"
          />
        </div>

        {isOpen && (
          <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md2 border border-border bg-surface shadow-cardHover">
            {isLoading ? (
              <p className="px-3.5 py-2.5 text-xs text-muted">Loading distribution groups…</p>
            ) : loadError ? (
              <p className="px-3.5 py-2.5 text-xs text-destructive">
                Couldn&apos;t load distribution groups. Please try again.
              </p>
            ) : filtered.length === 0 ? (
              <p className="px-3.5 py-2.5 text-xs text-muted">No matching distribution groups.</p>
            ) : (
              filtered.map((list) => (
                <button
                  type="button"
                  key={list.distribution_list_id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    add(list.distribution_list_id);
                  }}
                  className="flex w-full flex-col items-start px-3.5 py-1.5 text-left text-sm text-slate-900 transition-colors hover:bg-surfaceHover"
                >
                  <span className="font-medium">
                    {list.name} <span className="text-[11px] text-muted">· {list.member_count} members</span>
                  </span>
                  {list.description && <span className="text-[11px] text-muted">{list.description}</span>}
                </button>
              ))
            )}
          </div>
        )}
      </div>
      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{hint}</span>}
    </label>
  );
}
