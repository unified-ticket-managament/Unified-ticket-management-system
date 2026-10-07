"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { folderPathLabel } from "@tw/lib/folderTree";
import { Input } from "@/components/ui/input";
import { listMailFolders } from "@tw/api/mailFolder";
import type { MailFolder } from "@tw/types";

interface FolderPickerProps {
  value: string;
  onChange: (folderName: string) => void;
}

// The "Move to Folder" action's folder field — a searchable combobox.
// The user can open the list and click an existing folder, or type
// straight into the field (mouse, or ArrowUp/ArrowDown + Enter; Escape
// closes). Typed text that names an existing folder (exact, case-
// insensitive, by name or full path) resolves to that folder's real
// name; any other non-empty text is accepted as a NEW folder name —
// the backend creates it when the rule is saved (get-or-create by
// name, rule_folder_sync.ensure_action_folders), so a rule can create
// a folder and move mail into it in one go. A note makes that explicit
// so a typo is visible before saving. Rules still bind by `name` — the
// only field RuleActionItem.folder_name accepts server-side; names are
// globally unique, and folder_id is used here only as a React key.
//
// Unlike this directory's other pickers (EmployeeMultiSelect,
// ClientPicker's multi-select mode), which stay always-expanded
// specifically because RuleBuilderDialog's scrollable container clips
// a floating/absolute popover, this is single-select and closes after
// a pick — so it opens inline (not absolute/portal) below its own
// field, staying just as clipping-safe while still behaving like a
// real dropdown.
export function FolderPicker({ value, onChange }: FolderPickerProps) {
  const [folders, setFolders] = useState<MailFolder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  // What the user has typed since last committing a choice; null means
  // "not editing — show the saved value".
  const [draft, setDraft] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const listboxId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listMailFolders()
      .then((result) => {
        setFolders(result);
        setLoadError(false);
      })
      .catch(() => setLoadError(true))
      .finally(() => setIsLoading(false));
  }, []);

  // Escape closes just this list, not the surrounding rule dialog:
  // Radix's dialog listens for Escape on `document` in the capture
  // phase, so only a window-level capture listener runs ahead of it.
  useEffect(() => {
    if (!isOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setIsOpen(false);
      setActiveIndex(-1);
    }
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [isOpen]);

  const query = (draft ?? "").trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!query) return folders;
    return folders.filter((f) => folderPathLabel(folders, f.folder_id).toLowerCase().includes(query));
  }, [folders, query]);

  // The one folder the typed text names exactly (by name or full path,
  // case-insensitive) — ambiguous or partial text resolves to nothing,
  // never a guess.
  function resolveExact(text: string): MailFolder | null {
    const q = text.trim().toLowerCase();
    if (!q) return null;
    const matches = folders.filter(
      (f) => f.name.trim().toLowerCase() === q || folderPathLabel(folders, f.folder_id).toLowerCase() === q
    );
    return matches.length === 1 ? matches[0] : null;
  }

  function commit(folder: MailFolder) {
    onChange(folder.name);
    setDraft(null);
    setIsOpen(false);
    setActiveIndex(-1);
  }

  function handleInput(text: string) {
    setDraft(text);
    setIsOpen(true);
    setActiveIndex(-1);
    // An exact match resolves to the existing folder; anything else is
    // a (trimmed) new folder name. Empty text clears the value.
    const exact = resolveExact(text);
    onChange(exact ? exact.name : text.trim());
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
        return;
      }
      if (filtered.length === 0) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((i) => (i + step + filtered.length) % filtered.length);
    } else if (e.key === "Enter") {
      // Never let Enter submit/save the surrounding rule dialog.
      e.preventDefault();
      if (isOpen && activeIndex >= 0 && filtered[activeIndex]) {
        commit(filtered[activeIndex]);
      } else {
        const exact = draft !== null ? resolveExact(draft) : null;
        if (exact) commit(exact);
      }
    }
  }

  function handleBlur(e: React.FocusEvent<HTMLDivElement>) {
    if (containerRef.current?.contains(e.relatedTarget as Node | null)) return;
    setIsOpen(false);
    setActiveIndex(-1);
    // Whitespace-only/empty draft is just "cleared".
    if (draft !== null && !draft.trim()) setDraft(null);
  }

  const inputText = draft ?? value;
  // Typed text that does not match an existing folder: it will be
  // created when the rule is saved (only once folders have loaded, so a
  // slow list never mislabels an existing folder as new).
  const isNewFolder =
    draft !== null && draft.trim() !== "" && !isLoading && !loadError && resolveExact(draft) === null;

  return (
    <div ref={containerRef} onBlur={handleBlur}>
      <div className="relative">
        <Input
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
          aria-label="Folder"
          autoComplete="off"
          placeholder="Search or select a folder…"
          value={inputText}
          onChange={(e) => handleInput(e.target.value)}
          onFocus={() => setIsOpen(true)}
          onClick={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          className="h-9 rounded-md bg-transparent px-3 pr-9"
        />
        <button
          type="button"
          aria-label="Toggle folder list"
          tabIndex={-1}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setIsOpen((open) => !open)}
          className="absolute inset-y-0 right-0 flex w-9 items-center justify-center"
        >
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
      </div>

      {isNewFolder && (
        <p role="status" className="mt-1 text-xs text-muted-foreground">
          New folder “{draft?.trim()}” will be created when this rule is saved.
        </p>
      )}

      {isOpen && (
        <div className="mt-1 rounded-lg border border-border">
          <div id={listboxId} role="listbox" className="max-h-48 overflow-y-auto p-2">
            {isLoading ? (
              <p className="px-1 py-2 text-xs text-muted-foreground">Loading folders…</p>
            ) : loadError ? (
              <p className="px-1 py-2 text-xs text-destructive">
                Couldn't load folders. Please try again.
              </p>
            ) : folders.length === 0 ? (
              <p className="px-1 py-2 text-xs text-muted-foreground">No folders exist yet.</p>
            ) : filtered.length === 0 ? (
              <p className="px-1 py-2 text-xs text-muted-foreground">No matching folders.</p>
            ) : (
              filtered.map((folder, index) => (
                <div
                  role="option"
                  id={`${listboxId}-${index}`}
                  aria-selected={folder.name === value}
                  key={folder.folder_id}
                  // mousedown (not click) + preventDefault keeps focus in
                  // the input, so the blur handler doesn't close the list
                  // before the pick registers.
                  onMouseDown={(e) => {
                    e.preventDefault();
                    commit(folder);
                  }}
                  className={`flex w-full cursor-pointer items-center rounded-md px-1 py-1.5 text-left text-sm hover:bg-muted/50 ${
                    folder.name === value ? "font-medium" : ""
                  } ${index === activeIndex || folder.name === value ? "bg-muted/50" : ""}`}
                >
                  {/* Rules still bind by (globally unique) name; the path
                      just shows where a nested folder lives. */}
                  {folderPathLabel(folders, folder.folder_id)}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
