"use client";

import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

import { FieldWrapper, fieldBase } from "@tw/components/common/FormField";
import { isValidEmailAddress } from "@tw/lib/validation";
import type { RecipientOption } from "@tw/components/common/RecipientCombobox";

// A multi-select recipient field that behaves like a standard email
// "To" combobox with chips: click to see existing options, type to
// filter them, select a suggestion or type a syntactically valid
// email not in the list, and press Enter/comma to turn either into a
// removable chip. Reuses RecipientOption (RecipientCombobox.tsx) as
// its suggestion shape and isValidEmailAddress (lib/validation.ts) as
// its only validation source — deliberately a new component rather
// than widening RecipientCombobox (single-select, used by Compose's
// Forward "To") or UserMultiSelect (chip-based but closed-roster-only,
// no free text, used by Internal Note's To/CC/BCC) in place, to avoid
// any regression risk to either one's sole existing caller.
export interface RecipientChip {
  email: string;
  // Pre-formatted display text (e.g. "Koushik PV <koushik@probeps.com>")
  // when the chip came from a matched suggestion; omitted for a
  // manually-typed address, which then just displays its own email.
  label?: string;
}

interface MultiRecipientComboboxProps {
  label?: string;
  hint?: string;
  options: RecipientOption[];
  // When present, options are rendered under a header per group name,
  // in this order (only non-empty groups render) — same convention as
  // RecipientCombobox/UserMultiSelect's own grouping.
  groupOrder?: string[];
  value: RecipientChip[];
  onChange: (chips: RecipientChip[]) => void;
  // Forces the dropdown/typed-text state closed when the caller's own
  // context changes (e.g. a different thread) — same convention as
  // RecipientCombobox's resetKey.
  resetKey: string;
  placeholder?: string;
  disabled?: boolean;
  emptyStateLabel?: string;
}

function chipLabel(chip: RecipientChip): string {
  return chip.label ?? chip.email;
}

function findExactMatch(options: RecipientOption[], email: string): RecipientOption | undefined {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return undefined;
  return options.find((option) => option.email.toLowerCase() === normalized);
}

export function MultiRecipientCombobox({
  label,
  hint,
  options,
  groupOrder,
  value,
  onChange,
  resetKey,
  placeholder = "Search name or email…",
  disabled = false,
  emptyStateLabel = "No matching contact — type a full email address and press Enter.",
}: MultiRecipientComboboxProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [invalidEntry, setInvalidEntry] = useState<string | null>(null);

  useEffect(() => {
    setIsOpen(false);
    setQuery("");
    setInvalidEntry(null);
  }, [resetKey]);

  const selectedEmails = useMemo(
    () => new Set(value.map((chip) => chip.email.toLowerCase())),
    [value]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return options.filter((option) => {
      if (selectedEmails.has(option.email.toLowerCase())) return false;
      if (!q) return true;
      return option.label.toLowerCase().includes(q) || option.email.toLowerCase().includes(q);
    });
  }, [options, query, selectedEmails]);

  const groups = useMemo(() => {
    if (!groupOrder) return null;
    return groupOrder
      .map((groupName) => ({
        groupName,
        items: filtered.filter((option) => option.group === groupName),
      }))
      .filter((g) => g.items.length > 0);
  }, [filtered, groupOrder]);

  function addChip(chip: RecipientChip) {
    // Case-insensitive duplicate check — silently no-ops (clears the
    // typed text, doesn't add a second chip) rather than showing an
    // error, since "already added" isn't really a mistake.
    if (selectedEmails.has(chip.email.toLowerCase())) {
      setQuery("");
      return;
    }
    onChange([...value, chip]);
    setQuery("");
    setInvalidEntry(null);
  }

  function selectOption(option: RecipientOption) {
    addChip({ email: option.email, label: option.label });
    setIsOpen(false);
  }

  function removeChip(email: string) {
    onChange(value.filter((chip) => chip.email.toLowerCase() !== email.toLowerCase()));
  }

  function commitTyped(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const matched = findExactMatch(options, trimmed);
    if (matched) {
      addChip({ email: matched.email, label: matched.label });
      return;
    }
    if (isValidEmailAddress(trimmed)) {
      addChip({ email: trimmed });
      return;
    }
    setInvalidEntry(trimmed);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      if (query.trim()) {
        e.preventDefault();
        commitTyped(query);
      }
      return;
    }
    if (e.key === "Backspace" && query === "" && value.length > 0) {
      removeChip(value[value.length - 1].email);
    }
  }

  function renderOptionRow(option: RecipientOption) {
    return (
      <button
        type="button"
        key={option.id}
        // onMouseDown (not onClick) fires before the input's onBlur
        // closes the dropdown — same convention as UserMultiSelect.tsx
        // and RecipientCombobox.tsx.
        onMouseDown={(e) => {
          e.preventDefault();
          selectOption(option);
        }}
        className="flex w-full flex-col items-start px-3.5 py-1.5 text-left text-sm text-slate-900 transition-colors hover:bg-surfaceHover"
      >
        <span className="font-medium">{option.label}</span>
        {option.sublabel && <span className="text-[11px] text-muted">{option.sublabel}</span>}
      </button>
    );
  }

  const field = (
    <div className="relative">
      <div
        className={`${fieldBase} flex flex-wrap items-center gap-1.5 ${disabled ? "" : "cursor-text"}`}
      >
        {value.map((chip) => (
          <span
            key={chip.email}
            className="inline-flex items-center gap-1 rounded-full border border-accent/15 bg-accent/10 px-2 py-0.5 text-[11px] font-semibold text-accent"
          >
            {chipLabel(chip)}
            {!disabled && (
              <button
                type="button"
                onClick={() => removeChip(chip.email)}
                aria-label={`Remove ${chip.email}`}
                className="rounded-full p-0.5 hover:bg-accent/20"
              >
                <X size={10} />
              </button>
            )}
          </span>
        ))}
        <input
          type="text"
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value);
            setInvalidEntry(null);
          }}
          onFocus={() => setIsOpen(true)}
          onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder={value.length === 0 ? placeholder : ""}
          className="min-w-[140px] flex-1 border-none bg-transparent p-0 py-0.5 text-sm text-slate-900 placeholder:text-muted/60 focus:outline-none focus:ring-0"
        />
      </div>

      {isOpen && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md2 border border-border bg-surface shadow-cardHover">
          {filtered.length === 0 ? (
            <p className="px-3.5 py-2.5 text-xs text-muted">{emptyStateLabel}</p>
          ) : groups ? (
            groups.map(({ groupName, items }) => (
              <div key={groupName}>
                <p className="px-3.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
                  {groupName}
                </p>
                {items.map(renderOptionRow)}
              </div>
            ))
          ) : (
            filtered.map(renderOptionRow)
          )}
        </div>
      )}

      {invalidEntry && (
        <p className="mt-1 text-[11px] text-destructive">
          Enter a valid email address. &quot;{invalidEntry}&quot; isn&apos;t valid.
        </p>
      )}
    </div>
  );

  if (label) {
    return (
      <FieldWrapper label={label} hint={hint}>
        {field}
      </FieldWrapper>
    );
  }

  return (
    <>
      {field}
      {hint && <span className="mt-1.5 block text-[11px] leading-relaxed text-muted">{hint}</span>}
    </>
  );
}
