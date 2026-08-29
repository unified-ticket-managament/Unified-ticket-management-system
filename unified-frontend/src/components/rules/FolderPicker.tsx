"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Input } from "@/components/ui/input";
import { listMailFolders } from "@tw/api/mailFolder";
import type { MailFolder } from "@tw/types";

interface FolderPickerProps {
  value: string;
  onChange: (folderName: string) => void;
}

// The "Move to Folder" action's folder field — a closed-by-default,
// searchable dropdown constrained to folders that already exist (no
// free text ever reaches onChange, only a click on a fetched row), so
// a typo can never silently spawn a new folder via the backend's
// get-or-create-by-name move_to_folder execution path. Submits the
// folder's `name` (still the only field RuleActionItem.folder_name
// accepts server-side — there is no folder_id on that schema);
// folder_id is used here only as the list's React key and to
// highlight the current selection.
//
// Unlike this directory's other pickers (EmployeeMultiSelect,
// ClientPicker's multi-select mode), which stay always-expanded
// specifically because RuleBuilderDialog's scrollable container clips
// a floating/absolute popover, this is single-select and closes after
// a pick — so it opens inline (not absolute/portal) below its own
// trigger, staying just as clipping-safe while still behaving like a
// real dropdown.
export function FolderPicker({ value, onChange }: FolderPickerProps) {
  const [folders, setFolders] = useState<MailFolder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    listMailFolders()
      .then((result) => {
        setFolders(result);
        setLoadError(false);
      })
      .catch(() => setLoadError(true))
      .finally(() => setIsLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return folders;
    return folders.filter((f) => f.name.toLowerCase().includes(q));
  }, [folders, query]);

  function select(folder: MailFolder) {
    onChange(folder.name);
    setIsOpen(false);
    setQuery("");
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex h-9 w-full items-center justify-between rounded-md border border-border bg-transparent px-3 text-sm"
      >
        <span className={value ? "" : "text-muted-foreground"}>
          {value || "Select a folder…"}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      </button>

      {isOpen && (
        <div className="mt-1 rounded-lg border border-border">
          <div className="border-b border-border p-2">
            <Input
              placeholder="Search folders…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-8"
              autoFocus
            />
          </div>
          <div className="max-h-48 overflow-y-auto p-2">
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
              filtered.map((folder) => (
                <button
                  type="button"
                  key={folder.folder_id}
                  onClick={() => select(folder)}
                  className={`flex w-full items-center rounded-md px-1 py-1.5 text-left text-sm hover:bg-muted/50 ${
                    folder.name === value ? "bg-muted/50 font-medium" : ""
                  }`}
                >
                  {folder.name}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
