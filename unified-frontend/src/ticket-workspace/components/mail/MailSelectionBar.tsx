"use client";

import {
  Archive,
  FilePlus,
  Flag,
  FolderInput,
  Forward as ForwardIcon,
  Link2,
  Loader2,
  Mail,
  MailOpen,
  Pin,
  PinOff,
  Reply as ReplyIcon,
  ReplyAll,
  Trash2,
  Undo2,
  X,
} from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { FolderMoveItems } from "@tw/components/mail/FolderMoveItems";
import { useMailBulk } from "@tw/components/mail/MailBulkContext";
import { areAllSelected, selectionLabel } from "@tw/lib/mailSelection";
import { buildBulkMenu, type BulkActionKey, type MessageActionRow } from "@tw/lib/messageActions";
import type { MailFolder } from "@tw/types";

interface MailSelectionBarProps {
  // Ids of the rows on the current page (what "select all visible" covers).
  visibleIds: readonly string[];
  // The selected rows, resolved from the loaded list — used both for the
  // count-independent eligibility of each action and as the run target.
  selectedRows: readonly MessageActionRow[];
  folders: MailFolder[];
}

const buttonClass =
  "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-foreground/80 transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

// "Select all visible" when nothing is selected; the bulk action
// toolbar once at least one message is. Only actions the user holds the
// permission for (and that apply to at least one selected message) are
// offered — the backend re-authorizes every message regardless.
export function MailSelectionBar({ visibleIds, selectedRows, folders }: MailSelectionBarProps) {
  const bulk = useMailBulk();
  if (!bulk) return null;

  const { selectedIds, busy, perms, selectAll, clear, runBulk } = bulk;
  const count = selectedIds.size;
  const allSelected = areAllSelected(selectedIds, visibleIds);

  const checkbox = (
    <Checkbox
      aria-label={allSelected ? "Deselect all" : "Select all visible"}
      checked={allSelected ? true : count > 0 ? "indeterminate" : false}
      onCheckedChange={() => (allSelected ? clear() : selectAll(visibleIds))}
      disabled={busy || visibleIds.length === 0}
    />
  );

  if (count === 0) {
    return (
      <div className="flex items-center gap-2 border-b border-border px-4 py-1.5 text-[11.5px] text-muted-foreground">
        {checkbox}
        <span>Select all visible</span>
      </div>
    );
  }

  const menu = buildBulkMenu(selectedRows, perms);

  // Trash offers nothing but Restore (and Clear) — the other actions are
  // for live mail.
  if (bulk.isTrash) {
    return (
      <div className="flex flex-wrap items-center gap-x-1 gap-y-1 border-b border-border bg-primary/5 px-3 py-1.5">
        {checkbox}
        <span className="mr-1 text-[12px] font-semibold text-foreground" aria-live="polite">
          {selectionLabel(count)}
        </span>
        {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        {menu.restore && (
          <button
            type="button"
            className={buttonClass}
            title="Restore"
            aria-label="Restore"
            disabled={busy}
            onClick={() => runBulk("restore", selectedRows)}
          >
            <Undo2 className="h-3.5 w-3.5" />
            <span className="hidden xl:inline">Restore</span>
          </button>
        )}
        <button
          type="button"
          className={cn(buttonClass, "ml-auto")}
          title="Clear selection"
          aria-label="Clear selection"
          disabled={busy}
          onClick={clear}
        >
          <X className="h-3.5 w-3.5" />
          <span className="hidden xl:inline">Clear</span>
        </button>
      </div>
    );
  }

  const run = (action: BulkActionKey) => runBulk(action, selectedRows);

  const action = (
    key: BulkActionKey,
    label: string,
    icon: React.ReactNode,
    className?: string
  ) =>
    menu[key] && (
      <button
        key={key}
        type="button"
        className={cn(buttonClass, className)}
        title={label}
        aria-label={label}
        disabled={busy}
        onClick={() => run(key)}
      >
        {icon}
        <span className="hidden xl:inline">{label}</span>
      </button>
    );

  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-1 border-b border-border bg-primary/5 px-3 py-1.5">
      {checkbox}
      <span className="mr-1 text-[12px] font-semibold text-foreground" aria-live="polite">
        {selectionLabel(count)}
      </span>
      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}

      {action("reply", "Reply", <ReplyIcon className="h-3.5 w-3.5" />)}
      {action("replyAll", "Reply All", <ReplyAll className="h-3.5 w-3.5" />)}
      {action("forward", "Forward", <ForwardIcon className="h-3.5 w-3.5" />)}
      {action("createTicket", "Create Ticket", <FilePlus className="h-3.5 w-3.5" />)}
      {action("linkTicket", "Link / Attach to Ticket", <Link2 className="h-3.5 w-3.5" />)}
      {action("archive", "Archive", <Archive className="h-3.5 w-3.5" />)}

      {menu.move && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className={buttonClass}
              title="Move to"
              aria-label="Move to"
              disabled={busy}
            >
              <FolderInput className="h-3.5 w-3.5" />
              <span className="hidden xl:inline">Move to</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-72 w-52 overflow-y-auto">
            {folders.length === 0 ? (
              <DropdownMenuItem disabled>No folders yet</DropdownMenuItem>
            ) : (
              <>
                <DropdownMenuLabel>Move to folder</DropdownMenuLabel>
                <FolderMoveItems
                  kind="dropdown"
                  folders={folders}
                  onPick={(folderId) => runBulk("move", selectedRows, { folderId })}
                />
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => runBulk("move", selectedRows, { folderId: null })}>
                  Unfiled
                </DropdownMenuItem>
              </>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {action("markRead", "Mark Read", <MailOpen className="h-3.5 w-3.5" />)}
      {action("markUnread", "Mark Unread", <Mail className="h-3.5 w-3.5" />)}
      {action("flag", "Flag", <Flag className="h-3.5 w-3.5" />)}
      {action("unflag", "Unflag", <Flag className="h-3.5 w-3.5 fill-destructive text-destructive" />)}
      {action("pin", "Pin", <Pin className="h-3.5 w-3.5" />)}
      {action("unpin", "Unpin", <PinOff className="h-3.5 w-3.5" />)}
      {action("delete", "Delete", <Trash2 className="h-3.5 w-3.5" />, "text-destructive hover:text-destructive")}

      <button
        type="button"
        className={cn(buttonClass, "ml-auto")}
        title="Clear selection"
        aria-label="Clear selection"
        disabled={busy}
        onClick={clear}
      >
        <X className="h-3.5 w-3.5" />
        <span className="hidden xl:inline">Clear</span>
      </button>
    </div>
  );
}
