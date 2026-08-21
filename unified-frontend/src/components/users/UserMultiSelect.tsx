"use client";

import { useMemo, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Deliberately minimal/generic, same convention as the ticket-
// workspace's own SelectableUser (@tw/components/common/UserMultiSelect)
// — not tied to any one API's response shape, so this stays reusable
// regardless of where a caller's candidate list comes from.
export interface SelectableUser {
  user_id: string;
  name: string;
  email: string;
}

interface UserMultiSelectProps {
  users: SelectableUser[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  placeholder?: string;
  className?: string;
}

// Same chip/search/dropdown pattern as CategoryMultiSelect.tsx, over
// users instead of categories — this app's own shadcn tokens
// (border-border/bg-background/bg-popover/Badge), not the ticket-
// workspace's design system, so it visually matches the rest of this
// page instead of looking foreign. Used by the Categories page's
// Create/Edit forms for the Team Leads and Staff pickers.
export function UserMultiSelect({
  users,
  selectedIds,
  onChange,
  placeholder = "Select users…",
  className,
}: UserMultiSelectProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  const selectedUsers = useMemo(
    () => selectedIds.map((id) => users.find((u) => u.user_id === id)).filter(Boolean) as SelectableUser[],
    [users, selectedIds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return users.filter((user) => {
      if (selectedIds.includes(user.user_id)) return false;
      if (!q) return true;
      return user.name.toLowerCase().includes(q) || user.email.toLowerCase().includes(q);
    });
  }, [users, query, selectedIds]);

  function addUser(userId: string) {
    onChange([...selectedIds, userId]);
    setQuery("");
  }

  function removeUser(userId: string) {
    onChange(selectedIds.filter((id) => id !== userId));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && selectedUsers.length > 0) {
      removeUser(selectedUsers[selectedUsers.length - 1].user_id);
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
        {selectedUsers.map((user) => (
          <Badge key={user.user_id} variant="secondary" className="gap-1 pr-1">
            {user.name}
            <button
              type="button"
              onClick={() => removeUser(user.user_id)}
              aria-label={`Remove ${user.name}`}
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
          placeholder={selectedUsers.length === 0 ? placeholder : ""}
          className="min-w-[140px] flex-1 border-none bg-transparent p-0 py-0.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-0"
        />
      </div>

      {isOpen && (
        <div className="absolute z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-border bg-popover text-popover-foreground shadow-md">
          {filtered.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-muted-foreground">No matching users.</p>
          ) : (
            filtered.map((user) => (
              <button
                type="button"
                key={user.user_id}
                // onMouseDown (not onClick) fires before the input's
                // onBlur closes the dropdown.
                onMouseDown={(e) => {
                  e.preventDefault();
                  addUser(user.user_id);
                }}
                className="flex w-full flex-col items-start px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <span className="font-medium">{user.name}</span>
                <span className="text-xs text-muted-foreground">{user.email}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
