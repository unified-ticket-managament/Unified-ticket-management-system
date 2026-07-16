import { useMemo, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import type { RbacUserSummary } from "@tw/api/rbacUsers";

interface UserMultiSelectProps {
  label: string;
  hint?: string;
  placeholder?: string;
  // Role name -> active users holding that role, plus the fixed
  // display order for role groups — passed in rather than refetched
  // here so To/CC/BCC all share one listRbacUsers()/listRbacRoles()
  // fetch.
  groups: Record<string, RbacUserSummary[]>;
  roleOrder: string[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

const fieldBase =
  "w-full rounded-md2 border border-border bg-surface px-3.5 py-2 text-sm text-slate-900 " +
  "shadow-xs transition-all duration-150 focus-within:border-accent focus-within:outline-none " +
  "focus-within:ring-4 focus-within:ring-accent/10";

export function UserMultiSelect({
  label,
  hint,
  placeholder = "Search by name, email, or role…",
  groups,
  roleOrder,
  selectedIds,
  onChange,
}: UserMultiSelectProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  const allUsers = useMemo(() => {
    const withRole: { user: RbacUserSummary; roleName: string }[] = [];
    for (const roleName of roleOrder) {
      for (const user of groups[roleName] ?? []) {
        withRole.push({ user, roleName });
      }
    }
    return withRole;
  }, [groups, roleOrder]);

  const selectedUsers = useMemo(
    () => selectedIds.map((id) => allUsers.find((u) => u.user.user_id === id)).filter(Boolean) as {
      user: RbacUserSummary;
      roleName: string;
    }[],
    [allUsers, selectedIds]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allUsers.filter(({ user, roleName }) => {
      if (selectedIds.includes(user.user_id)) return false;
      if (!q) return true;
      return (
        user.name.toLowerCase().includes(q) ||
        user.email.toLowerCase().includes(q) ||
        roleName.toLowerCase().includes(q)
      );
    });
  }, [allUsers, query, selectedIds]);

  function addUser(userId: string) {
    onChange([...selectedIds, userId]);
    setQuery("");
  }

  function removeUser(userId: string) {
    onChange(selectedIds.filter((id) => id !== userId));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && query === "" && selectedUsers.length > 0) {
      removeUser(selectedUsers[selectedUsers.length - 1].user.user_id);
    }
  }

  const groupedFiltered = roleOrder.filter((roleName) =>
    filtered.some((f) => f.roleName === roleName)
  );

  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate-600">{label}</span>
      <div className="relative">
        <div className={`${fieldBase} flex flex-wrap items-center gap-1.5 cursor-text`}>
          {selectedUsers.map(({ user }) => (
            <span
              key={user.user_id}
              className="inline-flex items-center gap-1 rounded-full border border-accent/15 bg-accent/10 px-2 py-0.5 text-[11px] font-semibold text-accent"
            >
              {user.name}
              <button
                type="button"
                onClick={() => removeUser(user.user_id)}
                aria-label={`Remove ${user.name}`}
                className="rounded-full p-0.5 hover:bg-accent/20"
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
            placeholder={selectedUsers.length === 0 ? placeholder : ""}
            className="min-w-[120px] flex-1 border-none bg-transparent p-0 py-0.5 text-sm text-slate-900 placeholder:text-muted/60 focus:outline-none focus:ring-0"
          />
        </div>

        {isOpen && (
          <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md2 border border-border bg-surface shadow-cardHover">
            {filtered.length === 0 ? (
              <p className="px-3.5 py-2.5 text-xs text-muted">No matching internal users.</p>
            ) : (
              groupedFiltered.map((roleName) => (
                <div key={roleName}>
                  <p className="px-3.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">
                    {roleName}
                  </p>
                  {filtered
                    .filter((f) => f.roleName === roleName)
                    .map(({ user }) => (
                      <button
                        type="button"
                        key={user.user_id}
                        // onMouseDown (not onClick) fires before the
                        // input's onBlur closes the dropdown.
                        onMouseDown={(e) => {
                          e.preventDefault();
                          addUser(user.user_id);
                        }}
                        className="flex w-full flex-col items-start px-3.5 py-1.5 text-left text-sm text-slate-900 transition-colors hover:bg-surfaceHover"
                      >
                        <span className="font-medium">{user.name}</span>
                        <span className="text-[11px] text-muted">{user.email}</span>
                      </button>
                    ))}
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
