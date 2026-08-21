"use client";

import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

import { FieldWrapper, fieldBase } from "@tw/components/common/FormField";
import { isValidEmailAddress } from "@tw/lib/validation";

// A single-select "To" field that behaves like a standard email
// recipient combobox: click to see existing options, type to filter
// them, or type a syntactically valid email that isn't in the list at
// all and use it as-is. Deliberately separate from UserMultiSelect.tsx
// (multi-select, chip-based, closed-list-only, shared with Internal
// Note and a shell-app page) rather than extending it, to avoid any
// regression risk there.
export interface RecipientOption {
  id: string;
  label: string;
  email: string;
  sublabel?: string;
  group?: string;
}

interface RecipientComboboxProps {
  label?: string;
  hint?: string;
  options: RecipientOption[];
  // When present, options are rendered under a header per group name,
  // in this order (only non-empty groups render) — mirrors
  // UserMultiSelect.tsx's own roleOrder grouping convention.
  groupOrder?: string[];
  value: string;
  onChange: (result: { email: string; matchedOption?: RecipientOption }) => void;
  // Forces the dropdown closed when the caller's own context changes
  // (a different ticket, or a different message being forwarded) —
  // `value` itself is already reset by the caller's own existing
  // effect for that transition, so this only needs to cover the
  // transient open/closed UI state, not the value itself.
  resetKey: string;
  placeholder?: string;
  disabled?: boolean;
  // Lets each caller keep its own existing visual language (Reply's
  // ticket-workspace FormField look vs. Forward's shadcn Input look)
  // instead of forcing one style onto both.
  inputClassName?: string;
  emptyStateLabel?: string;
  // Set false when the caller already renders its own invalid-email
  // message from the same value (e.g. ComposeView.tsx's pre-existing
  // invalidToEntries block, reused for Forward) — avoids showing the
  // same complaint twice.
  showInlineError?: boolean;
}

function findExactMatch(options: RecipientOption[], email: string): RecipientOption | undefined {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return undefined;
  return options.find((option) => option.email.toLowerCase() === normalized);
}

export function RecipientCombobox({
  label,
  hint,
  options,
  groupOrder,
  value,
  onChange,
  resetKey,
  placeholder = "Select a contact or type an email…",
  disabled = false,
  inputClassName,
  emptyStateLabel = "No matching contact — the typed address will be used as-is.",
  showInlineError = true,
}: RecipientComboboxProps) {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    setIsOpen(false);
  }, [resetKey]);

  const query = value.trim().toLowerCase();

  const filtered = useMemo(() => {
    if (!query) return options;
    return options.filter(
      (option) =>
        option.label.toLowerCase().includes(query) || option.email.toLowerCase().includes(query)
    );
  }, [options, query]);

  const groups = useMemo(() => {
    if (!groupOrder) return null;
    return groupOrder
      .map((groupName) => ({
        groupName,
        items: filtered.filter((option) => option.group === groupName),
      }))
      .filter((g) => g.items.length > 0);
  }, [filtered, groupOrder]);

  const trimmedValue = value.trim();
  const matchedOption = useMemo(
    () => findExactMatch(options, trimmedValue),
    [options, trimmedValue]
  );
  const isInvalid = trimmedValue.length > 0 && !matchedOption && !isValidEmailAddress(trimmedValue);

  function selectOption(option: RecipientOption) {
    onChange({ email: option.email, matchedOption: option });
    setIsOpen(false);
  }

  function handleInputChange(nextValue: string) {
    onChange({ email: nextValue, matchedOption: findExactMatch(options, nextValue) });
  }

  function renderOptionRow(option: RecipientOption) {
    return (
      <button
        type="button"
        key={option.id}
        // onMouseDown (not onClick) fires before the input's onBlur
        // closes the dropdown — same convention as UserMultiSelect.tsx
        // and ComposeView.tsx's own contact-suggestion dropdown.
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
      <div className="relative">
        <input
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => setIsOpen(true)}
          onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
          placeholder={placeholder}
          className={inputClassName ?? `${fieldBase} cursor-text`}
          aria-invalid={isInvalid}
        />
        {value.length > 0 && !disabled && (
          <button
            type="button"
            onClick={() => onChange({ email: "" })}
            aria-label="Clear recipient"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
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

      {showInlineError && isInvalid && (
        <p className="mt-1 text-[11px] text-destructive">
          &quot;{trimmedValue}&quot; isn&apos;t a valid email address.
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
