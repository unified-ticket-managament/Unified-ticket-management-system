import { useEffect, useMemo, useRef, useState } from "react";

export interface SearchableSelectOption {
  value: string;
  label: string;
  // Lowercased text this option matches against as the user types —
  // typically name + employee ID, so both are searchable.
  searchText: string;
  // Heading this option renders under. An empty string renders the
  // option with no heading at all, above every named group — used
  // for a "Myself" self-assign entry, matching the plain, ungrouped
  // <option> the old native <select> rendered it as.
  group: string;
}

interface SearchableSelectProps {
  label: string;
  hint?: string;
  placeholder?: string;
  options: SearchableSelectOption[];
  value: string;
  onChange: (value: string) => void;
  emptyMessage?: string;
}

const fieldBase =
  "w-full rounded-md2 border border-border bg-surface px-3.5 py-2.5 text-sm text-slate-900 " +
  "placeholder:text-muted/60 shadow-xs transition-all duration-150 " +
  "focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/10";

// A single-select combobox: type to filter the option list in place,
// or just open the list (focus, no typing) and click through it —
// one field doing what used to take a separate search TextInput plus
// a native grouped <select> (see TicketActions.tsx's Transfer
// Ticket/Assign to Staff picker, its only caller today). Options are
// grouped for display only; every option stays selectable regardless
// of which group it's under.
export function SearchableSelect({
  label,
  hint,
  placeholder = "Search…",
  options,
  value,
  onChange,
  emptyMessage = "No matching results.",
}: SearchableSelectProps) {
  const selected = useMemo(() => options.find((o) => o.value === value) ?? null, [options, value]);
  const [query, setQuery] = useState(selected?.label ?? "");
  const [isOpen, setIsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keeps the displayed text in sync with the selected value when it
  // changes from outside (e.g. the modal picking a default candidate
  // before this ever mounts) — never while the dropdown is open,
  // so this can't stomp on the user's own in-progress typing.
  useEffect(() => {
    if (!isOpen) setQuery(selected?.label ?? "");
  }, [selected, isOpen]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    // Still showing the selected option's own label (just
    // opened/focused, nothing typed yet) counts as "no filter" —
    // opening the dropdown should show every candidate, not just the
    // one already picked.
    if (!q || q === selected?.label.toLowerCase()) return options;
    return options.filter((o) => o.searchText.includes(q));
  }, [options, query, selected]);

  const groupOrder = useMemo(() => {
    const seen: string[] = [];
    for (const option of filtered) {
      if (!seen.includes(option.group)) seen.push(option.group);
    }
    return seen;
  }, [filtered]);

  function selectOption(option: SearchableSelectOption) {
    onChange(option.value);
    setQuery(option.label);
    setIsOpen(false);
  }

  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate-600">{label}</span>
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIsOpen(true);
          }}
          onFocus={(e) => {
            setIsOpen(true);
            e.target.select();
          }}
          // onMouseDown on an option below fires before this blur
          // closes the dropdown, so a click-to-select is never lost.
          onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
          placeholder={placeholder}
          className={`${fieldBase} cursor-text`}
        />

        {isOpen && (
          <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md2 border border-border bg-surface shadow-cardHover">
            {filtered.length === 0 ? (
              <p className="px-3.5 py-2.5 text-xs text-muted">{emptyMessage}</p>
            ) : (
              groupOrder.map((groupName) => (
                <div key={groupName || "__ungrouped"}>
                  {groupName && (
                    <p className="px-3.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
                      {groupName}
                    </p>
                  )}
                  {filtered
                    .filter((o) => o.group === groupName)
                    .map((option) => (
                      <button
                        type="button"
                        key={option.value}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          selectOption(option);
                        }}
                        className={`block w-full px-3.5 py-1.5 text-left text-sm transition-colors hover:bg-surfaceHover ${
                          option.value === value ? "bg-accent/5 font-medium text-accent" : "text-slate-900"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))
                  }
                </div>
              ))
            )}
          </div>
        )}
      </div>
      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{hint}</span>}
    </label>
  );
}
