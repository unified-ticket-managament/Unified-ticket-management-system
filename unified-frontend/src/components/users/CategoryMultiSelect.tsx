"use client";

import { useMemo, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Category } from "@/types";

interface CategoryMultiSelectProps {
  categories: Category[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  placeholder?: string;
  className?: string;
}

// Small, purpose-built multi-select for Categories — mirrors the
// ticket-workspace's own UserMultiSelect chip/search/dropdown pattern
// (see src/ticket-workspace/components/common/UserMultiSelect.tsx),
// re-themed with this shell app's own shadcn tokens instead of the
// ticket-workspace's `.tm-scope` utility classes, and with no
// role-grouping since there's nothing to group here — a flat,
// typically-small list of categories. Used both by the Users page's
// Category filter and the Create/Edit User form.
export function CategoryMultiSelect({
  categories,
  selectedIds,
  onChange,
  placeholder = "Select categories…",
  className,
}: CategoryMultiSelectProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  const selectedCategories = useMemo(
    () => selectedIds.map((id) => categories.find((c) => c.category_id === id)).filter(Boolean) as Category[],
    [categories, selectedIds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return categories.filter((category) => {
      if (selectedIds.includes(category.category_id)) return false;
      if (!q) return true;
      return category.category_name.toLowerCase().includes(q);
    });
  }, [categories, query, selectedIds]);

  function addCategory(categoryId: string) {
    onChange([...selectedIds, categoryId]);
    setQuery("");
  }

  function removeCategory(categoryId: string) {
    onChange(selectedIds.filter((id) => id !== categoryId));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && selectedCategories.length > 0) {
      removeCategory(selectedCategories[selectedCategories.length - 1].category_id);
    }
  }

  return (
    <div className={cn("relative", className)}>
      <div
        className={cn(
          "flex min-h-10 w-full flex-wrap items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-sm",
          "cursor-text focus-within:outline-none focus-within:ring-2 focus-within:ring-ring"
        )}
      >
        {selectedCategories.map((category) => (
          <Badge key={category.category_id} variant="secondary" className="gap-1 pr-1">
            {category.category_name}
            <button
              type="button"
              onClick={() => removeCategory(category.category_id)}
              aria-label={`Remove ${category.category_name}`}
              className="rounded-full p-0.5 hover:bg-muted"
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setIsOpen(true)}
          onBlur={() => window.setTimeout(() => setIsOpen(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder={selectedCategories.length === 0 ? placeholder : ""}
          className="min-w-[100px] flex-1 border-none bg-transparent p-0 py-0.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-0"
        />
      </div>

      {isOpen && (
        <div className="absolute z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-border bg-popover text-popover-foreground shadow-md">
          {filtered.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-muted-foreground">No matching categories.</p>
          ) : (
            filtered.map((category) => (
              <button
                type="button"
                key={category.category_id}
                // onMouseDown (not onClick) fires before the input's
                // onBlur closes the dropdown.
                onMouseDown={(e) => {
                  e.preventDefault();
                  addCategory(category.category_id);
                }}
                className="flex w-full items-center px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                {category.category_name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
